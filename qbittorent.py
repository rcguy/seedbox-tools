#!/home/rcguy/python-projects/seedbox/venv/bin/python3
# -*- coding: utf-8 -*-

#
# qbt_tools.py - Simple tools for managing qBittorrent using the qbittorrent-api Python library
#
# Copyright (C) 2026 rcguy
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Author - rcguy
# Created - 2026-03-16
# Updated - 2026-03-30
# Version - 1.2.0
# Requires - loguru pyyaml qbittorrent-api
#

import os
import sys
import argparse
import re
import yaml
import qbittorrentapi
from datetime import datetime
from loguru import logger
from my_utils import make_dir, load_yaml
from models.torrent_info import TorrentInfo


def cli() -> object:
    """Command Line Interface"""

    # https://stackoverflow.com/a/44333798
    formatter = lambda prog: argparse.HelpFormatter(prog, width=256, max_help_position=64)

    parser = argparse.ArgumentParser(description="qBittorrent Python Tools", formatter_class=formatter)
    
    parser.add_argument("-P", "--path",
                        type=str,
                        default=None,
                        help="save path for adding torrents to client (see --torrents-add)")
    
    parser.add_argument("-C", "--config",
                        type=str,
                        default=None,
                        help="config file path")

    parser.add_argument("-d", "--export-dir",
                        type=str,
                        default=None,
                        help="export .torrent files to this directory")

    parser.add_argument("-c", "--category",
                        type=str,
                        default=None,
                        help="filter torrents by category")

    parser.add_argument("-s", "--status",
                        type=str,
                        default="seeding",
                        metavar="STATUS",
                        choices=["all", "downloading", "seeding", "completed", "paused", "stopped", "active", "inactive", "resumed", "running", "stalled", "stalled_uploading", "stalled_downloading", "checking", "moving", "errored"],
                        help="filter torrents by status")

    parser.add_argument("-t", "--tag",
                        type=str,
                        default=None,
                        help="filter torrents by tag")

    parser.add_argument("-k", "--skip-labels",
                        type=str,
                        nargs="+",
                        default=None,
                        help="skip torrents with these categories/labels when performing commands")
    
    parser.add_argument("-S", "--seed-time",
                        type=int,
                        default=None,
                        help="minimum seed time in seconds before removing torrents from client")
    
    parser.add_argument("-n", "--nvme-time",
                        type=int,
                        default=None,
                        help="minimum time in seconds that torrent has been on NVMe before moving to Spinning Rust")

    commands = parser.add_argument_group('commands')

    commands.add_argument("-T", "--add-torrents",
                        type=str,
                        nargs="+",
                        default=None,
                        metavar="FILES",
                        help="add .torrent files to client with this save path and category (see --category)")
    
    commands.add_argument("-A", "--autoremove",
                        action='store_true',
                        help="remove torrents that have been seeding for more than N seconds (see --seed-time)")
    
    commands.add_argument("-U", "--unregistered",
                        action='store_true',
                        help='remove unregistered torrents from client')

    commands.add_argument("-L", "--list-torrents",
                        action="store_true",
                        help="list all torrents in client")

    commands.add_argument("-M", "--move-torrents",
                        action="store_true",
                        help="move torrents from NVMe to Spinning Rust after N seconds (see --nvme-time)")
    
    commands.add_argument("-E", "--export-torrents",
                        action="store_true",
                        help="export all .torrent files from client")

    commands.add_argument("-D", "--dry-run",
                        action="store_true",
                        help="perform a trial run with no changes made")

    return parser.parse_args()


def get_torrents(client: qbittorrentapi.Client, status_filter: str, category_filter:str, tag_filter: str) -> list:
    """Get list of all torrents in the client"""

    try:
        logger.info("Getting list of all torrents...")
        raw = client.torrents_info(status_filter=status_filter, category=category_filter, tag=tag_filter, sort="seeding_time")
        logger.info(f"Found {len(raw)} torrents")

        mapped = []
        for t in raw:
            ti = TorrentInfo(
                name=getattr(t, "name", None),
                category=getattr(t, "category", None),
                tags=getattr(t, "tags", None),
                infohash=getattr(t, "infohash_v1", getattr(t, "hash", None)),
                save_path=getattr(t, "save_path", None),
                timestamp_finished=getattr(t, "completion_on", None),
                message=None,
                session_file=None,
                seeding_time=getattr(t, "seeding_time", None),
            )
            mapped.append(ti)

        return mapped
    except Exception as err:
        logger.error(err)
        sys.exit(1)


def list_torrents(torrent_list: list) -> None:
    """Print list of torrents in client"""

    if torrent_list:
        for torrent in torrent_list:
            logger.debug(f"{(torrent.infohash or '')[-6:]}: {torrent.name} cat={torrent.category} tags={torrent.tags} seed_time={torrent.seeding_time} path={torrent.save_path} ")
    else:
        logger.error("List of torrents is empty!")


def move_torrents(client: qbittorrentapi.Client, torrent_list: list) -> None:
    """Move torrent files from NVMe to Spinning Rust after N seconds"""

    if torrent_list:
        logger.info("Searching for torrents to move...")
        
        for torrent in torrent_list:
            data_path = os.path.join(torrent.save_path, torrent.name)
            root_path = os.path.commonpath([data_path, nvme_dir])

            if (torrent.seeding_time or 0) > nvme_time and root_path == nvme_dir:
                torrent_directory = os.path.join(rust_dir, torrent.category)
                logger.info(f"Moving {torrent.name} to {torrent_directory}")

                if not dry_run:
                    client.torrents_set_location(location=torrent_directory, torrent_hashes=torrent.infohash)
    else:
        logger.error("List of torrents is empty!")


def export_torrents(client: qbittorrentapi.Client, backup_dir: str, torrent_list: list) -> None:
    """Copy all torrents from qBittorent to backup dir"""

    if torrent_list:
        logger.info(f"Copying all .torrent files to: {backup_dir}")
        export_date = datetime.now().strftime("%Y-%m-%dT%H%M%S")

        for torrent in torrent_list:
            torrent_name = torrent.name
            torrent_output_path = os.path.join(backup_dir, export_date, torrent.category)
            torrent_output_file = os.path.join(torrent_output_path, f"{torrent_name}.torrent")

            if not os.path.exists(torrent_output_file):
                try:
                    if not dry_run:
                        make_dir(torrent_output_path)
                        torrent_file_bytes = client.torrents_export(torrent_hash=torrent.infohash)
                        with open(torrent_output_file, "wb") as fh:
                            fh.write(torrent_file_bytes)
                    logger.debug(f"Exported .torrent: {torrent_name}")
                except FileNotFoundError:
                    logger.error(f"No such file or directory: '{torrent_output_file}'")
                    continue
            else:
                logger.warning(f"Torrent Exists: {torrent_output_file}")
    else:
        logger.error("List of torrents is empty!")


def unregistered_torrents(client: qbittorrentapi.Client, torrent_list: list) -> None:
    """Delete unregistered torrents from client"""

    if torrent_list:
        torrents_to_delete = list()
        logger.info("Searching for unregistered torrents...")

        for torrent in torrent_list:
            torrent_infohash = torrent.infohash
            torrent_tracker = client.torrents_trackers(torrent_hash=torrent_infohash)
            unregistered = re.search("Unregistered", getattr(torrent_tracker[-1], 'msg', '') if torrent_tracker else "")
            label_allowed = False if torrent.category in skip_labels else True

            if unregistered and label_allowed:
                torrents_to_delete.append(torrent_infohash)
                logger.debug(f"Unregistered torrent found: {torrent.name}")

        if not dry_run and torrents_to_delete:
            try:
                logger.info(f"Deleting {len(torrents_to_delete)} unregistered torrents from client...")
                client.torrents_delete(delete_files=True, torrent_hashes=torrents_to_delete)
            except Exception as err:
                logger.error(err)
        else:
            logger.info("No unregistered torrents found!")
    else:
        logger.error("List of torrents is empty!")


def autoremove_torrents(client: qbittorrentapi.Client, torrent_list: list) -> None:
    """Delete torrents that have been seeding for more than N hours"""

    if torrent_list:
        torrents_to_delete = list()
        logger.info("Searching for torrents to autoremove...")

        for torrent in torrent_list:
            torrent_seed_time = (torrent.seeding_time or 0) // 3600 # hours
            torrent_category = torrent.category
            seed_time = category_seed_time.get(torrent_category, minimum_seed_time)
            
            if torrent_seed_time > seed_time and torrent_category not in skip_labels:
                torrents_to_delete.append(torrent.infohash)
                logger.debug(f"Torrent found: seed_time={torrent_seed_time} - {torrent.name} ")

        if not dry_run and torrents_to_delete:
            try:
                logger.info(f"Deleting {len(torrents_to_delete)} torrents older then {minimum_seed_time} hours from client...")
                client.torrents_delete(delete_files=True, torrent_hashes=torrents_to_delete)
            except Exception as err:
                logger.error(err)
        else:
            logger.info("No torrents found to autoremove!")
    else:
        logger.error("List of torrents is empty!")


def upload_torrents(client: qbittorrentapi.Client, torrent_files: list, save_directory: str, category: str, tags: str) -> None:
    """Upload .torrent files to qBittorrent"""

    if torrent_files:
        for torrent_file in torrent_files:
            try:
                client.torrents_add(torrent_files=torrent_file, save_path=save_directory, category=category, tags=tags, is_paused=True)
                logger.info(f"Uploaded torrent to qBittorrent: {os.path.basename(torrent_file)}")
            except Exception as err:
                logger.error(err)
                continue
    else:
        logger.error("List of .torrent files is empty!")


if __name__ == "__main__":

    script_cwd = os.path.abspath(os.path.dirname(__file__))
    logger.add(os.path.join(script_cwd, "logs/qbittorrent_tools.log"),
        format="{time} - {level} - {message}",
        level=20,
        rotation="1 week",
        compression="gz"
    )

    args = cli()
    dry_run = args.dry_run
    cfg_path = os.path.abspath(args.config) if args.config else os.path.join(script_cwd, "cfg/seedbox.yaml")
    cfg = load_yaml(cfg_path)["Seedbox"]
    skip_labels = cfg["skip_labels"] if not args.skip_labels else args.skip_labels
    category_seed_time = cfg["category_seed_time"]
    minimum_seed_time = cfg["minimum_seed_time"] if not args.seed_time else args.seed_time
    nvme_time = cfg["nvme_cache_time"] if not args.nvme_time else args.nvme_time
    nvme_dir = cfg["nvme_dir"]
    rust_dir = cfg["rust_dir"]
    export_dir = os.path.abspath(args.export_dir) if args.export_dir else os.path.join(script_cwd, cfg["export_dir"])
    conn_info = dict(
        host=cfg["qBittorrent"]["host"],
        port=cfg["qBittorrent"]["port"],
        username=cfg["qBittorrent"]["username"],
        password=cfg["qBittorrent"]["password"],
    )

    try:
        with qbittorrentapi.Client(**conn_info) as qbt_client:

            all_torrents = get_torrents(qbt_client, args.status, args.category, args.tag)

            if args.list_torrents:
                list_torrents(all_torrents)
            if args.unregistered:
                unregistered_torrents(qbt_client, all_torrents)  
            if args.move_torrents:
                move_torrents(qbt_client, all_torrents)
            if args.autoremove:
                autoremove_torrents(qbt_client, all_torrents)
            if args.export_torrents:
                export_torrents(qbt_client, export_dir, all_torrents)

            qbt_client.auth_log_out()
            sys.exit()

    except qbittorrentapi.LoginFailed as e:
        logger.error(e)
        sys.exit(1)
