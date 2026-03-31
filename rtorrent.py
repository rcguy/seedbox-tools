#!/home/rcguy/python-projects/seedbox/venv/bin/python3
# -*- coding: utf-8 -*-

#
# rtorrent_tools.py - Simple tools for managing rTorrent
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
# Version - 1.4.0
# Requires - loguru pyyaml rcguy_utils
#

import os
import sys
import time
import shutil
import argparse
import xmlrpc.client
import re
import yaml
from datetime import datetime
from loguru import logger
from my_utils import make_dir, delete_files, load_yaml, find_files, create_zip
from models.torrent_info import TorrentInfo


def cli() -> object:
    """Command Line Interface"""

    # https://stackoverflow.com/a/44333798
    formatter = lambda prog: argparse.HelpFormatter(prog, width=256, max_help_position=64)

    parser = argparse.ArgumentParser(description="rTorrent Python Tools", formatter_class=formatter)
    
    parser.add_argument("-p", "--path",
                        type=str,
                        default=None,
                        help="save path for adding torrents to client (see --torrents-add)")
    
    parser.add_argument("-c", "--config",
                        type=str,
                        default=None,
                        help="config file path")
    
    parser.add_argument("-l", "--label",
                        type=str,
                        default=None,
                        help="label for filtering or adding torrents to client (see --torrents-add)")

    parser.add_argument("-f", "--filter",
                        type=str,
                        default="seeding",
                        metavar="STATUS",
                        choices=["main", "default", "active", "started", "stopped", "complete", "incomplete", "hashing", "seeding", "leeching", "rat_0", "rat_1", "rat_2", "rat_3", "rat_4", "rat_5", "rat_6", "rat_7"],
                        help="filter torrents by status")
    
    parser.add_argument("-d", "--export-dir",
                        type=str,
                        default=None,
                        help="export .torrent files to this directory")

    parser.add_argument("-k", "--skip-labels",
                        type=str,
                        nargs="+",
                        default=None,
                        help="skip torrents with these labels when performing commands")
    
    parser.add_argument("-s", "--seed-time",
                        type=int,
                        default=None,
                        help="minimum seed time in hours before removing torrents from client")
    
    parser.add_argument("-n", "--nvme-time",
                        type=int,
                        default=None,
                        help="minimum time in seconds that torrent has been on NVMe before moving to Spinning Rust")

    parser.add_argument("-z", "--zip",
                        action="store_true",
                        help="create zip archive of exported torrents")

    commands = parser.add_argument_group('commands')

    commands.add_argument("-T", "--add-torrents",
                        type=str,
                        default="",
                        metavar="FILES",
                        help="add .torrent files to client with this save path and label (see --label and --path)")
    
    commands.add_argument("-A", "--autoremove",
                        action='store_true',
                        help="remove torrents that have been seeding for more than N hours (see --seed-time)")
    
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

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit()

    return parser.parse_args()


def get_torrents(server_url: str, status_filter: str = "seeding", category_filter: str | None = None) -> list:
    """Get list of all torrents in the client"""

    fields = ("d.name=", "d.custom1=", "d.hash=", "d.data_path=", "d.timestamp.finished=", "d.message=", "d.session_file=")

    try:
        logger.info("Getting list of all torrents...")
        with xmlrpc.client.ServerProxy(server_url) as rtorrent:
            if category_filter is not None:
                raw = rtorrent.d.multicall.filtered("", status_filter, f'equal=d.custom1=,cat={category_filter}', *fields)
            else:
                raw = rtorrent.d.multicall2("", status_filter, *fields)

            mapped = []
            for t in raw:
                seeding_time = (int(time.time()) - t[4]) if t[4] else 0

                ti = TorrentInfo(
                    name=t[0],
                    category=t[1],
                    tags=None,
                    infohash=t[2],
                    save_path=t[3],
                    timestamp_finished=t[4],
                    message=t[5],
                    session_file=t[6],
                    seeding_time=seeding_time,
                )
                mapped.append(ti)

            logger.info(f"Found {len(mapped)} torrents")
            return mapped
    except Exception as err:
        logger.error(err)
        sys.exit(1)


def list_torrents(torrent_list: list) -> None:
    """Print list of torrents in client"""

    if torrent_list:
        for torrent in torrent_list:
            #seeding_hours = (torrent.seeding_time // 3600) if torrent.seeding_time else None
            logger.debug(f"{(torrent.infohash or '')[-6:]}: {torrent.name} label='{torrent.category}' seed_time={torrent.seeding_time} path={torrent.save_path} session_file={torrent.session_file} tracker_status='{torrent.message}'")
    else:
        logger.error("List of torrents is empty!")


def move_torrents(server_url: str, torrent_list: list) -> None:
    """Move torrent files from NVMe to Spinning Rust after N seconds"""

    if torrent_list:
        logger.debug("Searching for torrents to move...")
        with xmlrpc.client.ServerProxy(server_url) as rtorrent:
            for torrent in torrent_list:
                root_path = os.path.commonpath([torrent.save_path, nvme_dir])
                
                if torrent.seeding_time or 0 > nvme_time and root_path == nvme_dir:
                    torrent_rel_path = os.path.relpath(torrent.save_path, nvme_dir)
                    torrent_move_path = os.path.join(rust_dir, torrent_rel_path)
                    torrent_directory = os.path.dirname(torrent_move_path)
                    logger.debug(f"{torrent_rel_path} - {torrent_move_path} - {torrent_directory}")

                    if not dry_run:
                        try:
                            logger.info(f"Moving {torrent.name} to {torrent_directory}")
                            if os.path.isfile(torrent.save_path):
                                make_dir(torrent_directory)
                                shutil.copy2(torrent.save_path, torrent_move_path)
                            elif os.path.isdir(torrent.save_path):
                                shutil.copytree(torrent.save_path, torrent_move_path)
                        except FileNotFoundError:
                            logger.error(f"No such file or directory: '{torrent.save_path}'")
                            continue
                        except FileExistsError:
                            logger.error(f"File exists: '{torrent_move_path}'")
                            continue
                        except PermissionError:
                            logger.error(f"Permission Denied: '{torrent_move_path}'")
                            continue    

                        multicall = xmlrpc.client.MultiCall(rtorrent)
                        multicall.d.stop(torrent.infohash)
                        multicall.d.directory.set(torrent.infohash, torrent_directory)
                        multicall.d.start(torrent.infohash)

                        multicall()
                        rtorrent.d.save_full_session(torrent.infohash)
                        delete_files(torrent.save_path)
                        
                        if sleep_time > 0:
                            logger.info(f"Sleeping for {sleep_time} seconds before moving next torrent...")
                            time.sleep(sleep_time)
    else:
        logger.error(f"List of torrents is empty!")


def unregistered_torrents(server_url: str, torrent_list: list) -> None:
    """Delete unregistered torrents from client"""

    if torrent_list:
        logger.info("Searching for unregistered torrents...")
        
        try:
            with xmlrpc.client.ServerProxy(server_url) as rtorrent:
                for torrent in torrent_list:
                    unregistered = re.search("Unregistered", torrent.message or "")
    
                    if not dry_run and unregistered and torrent.category not in skip_labels:
                        logger.debug(f"Unregistered torrent found: {torrent.name} tracker_status='{torrent.message}' path={os.path.dirname(torrent.save_path)} label='{torrent.category}'")
                        multicall = xmlrpc.client.MultiCall(rtorrent)
                        multicall.d.try_stop(torrent.infohash)
                        multicall.d.try_close(torrent.infohash)
                        multicall.d.erase(torrent.infohash)
                        multicall()
    
                        delete_files(torrent.save_path)
    
                logger.debug("Saving rTorrent session...")
                rtorrent.session.save()

        except Exception as err:
            logger.error(err)
            sys.exit(1)
    
    else:
        logger.error("List of torrents is empty!")


def export_torrents(backup_dir: str, torrent_list: list, zip_output: bool = False) -> None:
    """Copy all torrents from client to backup dir"""

    if torrent_list:
        logger.info(f"Copying all .torrent files to: {backup_dir}")
        export_date = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        backup_path = os.path.join(backup_dir, export_date)

        for torrent in torrent_list:
            torrent_output_path = os.path.join(backup_path, torrent.category)
            torrent_output_file = os.path.join(torrent_output_path, f"{torrent.name}.torrent")

            if not os.path.exists(torrent_output_file):
                try:
                    if not dry_run and os.path.isfile(torrent.session_file):
                        make_dir(torrent_output_path)
                        shutil.copy2(torrent.session_file, torrent_output_file)
                    logger.debug(f"Exported .torrent: {torrent.name}")
                except FileNotFoundError:
                    logger.error(f"No such file or directory: '{torrent.session_file}'")
                    continue
            else:
                logger.warning(f"Torrent Exists: {torrent_output_file}")

        if zip_output:
            zip_output_file = os.path.join(backup_dir, f"rTorrent_{export_date}.zip")
            logger.info(f"Creating zip archive of exported torrents: {zip_output_file}")
            create_zip(backup_path, zip_output_file)
            delete_files(backup_path)

    else:
        logger.error("List of torrents is empty!")


def upload_torrents(server_url: str, torrent_files: list, save_path: str, label: str, paused: bool = True) -> None:
    """Upload .torrent files to client with save path and label"""
    
    logger.debug("Uploading torrents...")
    try:
        with xmlrpc.client.ServerProxy(server_url) as rtorrent:
            make_dir(save_path)
            for torrent in torrent_files:
                with open(torrent, "rb") as fh:
                    rtorrent.load.raw_verbose("", xmlrpc.client.Binary(fh.read()), "d.delete_tied=", f"d.custom1.set={label}", f"d.directory.set={save_path}")
                    logger.info(f"Uploaded torrent: name='{os.path.basename(torrent)}' save_path='{save_path}' label='{label}'")
                    time.sleep(0.25)

            logger.debug(f"Uploaded {len(torrent_files)} .torrent files")

    except Exception as err:
        logger.error(err)
        sys.exit(1)


def autoremove_torrents(server_url: str, torrent_list: list) -> None:
    """Delete torrents that have been seeding for more than N hours"""

    if torrent_list:
        logger.info("Searching for torrents to autoremove...")

        try:
            with xmlrpc.client.ServerProxy(server_url) as rtorrent:
                for torrent in torrent_list:
                    torrent_seeding_time = torrent.seeding_time // 3600
                    torrent_min_seed_time = category_seed_time.get(torrent.category, minimum_seed_time)
            
                    if torrent_seeding_time > torrent_min_seed_time and torrent.category not in skip_labels:
                        logger.debug(f"Torrent found: seeding_time={torrent_seeding_time} - {torrent.name}")

                    if not dry_run:
                        multicall = xmlrpc.client.MultiCall(rtorrent)
                        multicall.d.try_stop(torrent.infohash)
                        multicall.d.try_close(torrent.infohash)
                        multicall.d.erase(torrent.infohash)
                        multicall()
            
                        delete_files(torrent.save_path)
            
                logger.debug("Saving rTorrent session...")
                rtorrent.session.save()

        except Exception as err:
            logger.error(err)
            sys.exit(1)
    else:
        logger.error("List of torrents is empty!")


if __name__ == "__main__":

    script_cwd = os.path.abspath(os.path.dirname(__file__))
    logger.add(os.path.join(script_cwd, "logs/rtorrent_tools.log"),
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
    sleep_time = cfg["sleep_time"]
    category_seed_time = cfg["category_seed_time"]
    minimum_seed_time = cfg["minimum_seed_time"] if not args.seed_time else args.seed_time
    nvme_time = cfg["nvme_cache_time"] if not args.nvme_time else args.nvme_time
    nvme_dir = cfg["nvme_dir"]
    rust_dir = cfg["rust_dir"]
    export_dir = os.path.abspath(args.export_dir) if args.export_dir else os.path.join(script_cwd, cfg["export_dir"], "rtorrent")
    client = cfg["rTorrent"]["server_url"]
    torrent_files = [args.add_torrents] if os.path.isfile(args.add_torrents) else find_files(args.add_torrents, ".torrent", False)

    try:

        if args.add_torrents:
            upload_torrents(client, torrent_files, args.path, args.label, paused=True)
            sys.exit()
            
        all_torrents = get_torrents(client, args.filter, args.label)

        if args.list_torrents:
            list_torrents(all_torrents)
        if args.unregistered:
            unregistered_torrents(client, all_torrents)  
        if args.move_torrents:
            move_torrents(client, all_torrents)
        if args.autoremove:
            autoremove_torrents(client, all_torrents)
        if args.export_torrents:
            export_torrents(export_dir, all_torrents, args.zip)

        sys.exit()

    except Exception as err:
        logger.error(err)
        sys.exit(1)