#
# qbittorrent.py - Simple class for managing qBittorrent
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
# Updated - 2026-03-31
# Version - 1.3.0
# Requires - loguru pyyaml qbittorrent-api
#

import os
import sys
import re
import qbittorrentapi
from datetime import datetime
from loguru import logger
from my_utils import make_dir, create_zip, delete_files
from models.torrent_info import TorrentInfo
from models.config import SeedboxConfig
from clients.base import TorrentClient


class qBittorrentClient(TorrentClient):
    """Class wrapper for qbittorrentapi.Client implementing TorrentClient."""

    def __init__(self) -> None:
        self.client = None

    def connect(self, config: SeedboxConfig):
        try:
            logger.info("Connecting to qBittorrent API...")
            self.client = qbittorrentapi.Client(**config.qbittorrent.conn_info)
        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def get_torrents(self, config: SeedboxConfig) -> list:
        """Get list of all torrents in the client"""
        try:
            logger.info("Getting list of all torrents...")
            raw = self.client.torrents_info(status_filter=config.torrent_status, category=config.torrent_label, tag=config.torrent_tag, sort="seeding_time")
            logger.info(f"Found {len(raw)} torrents")

            mapped = []
            for t in raw:
                ti = TorrentInfo(
                    name=getattr(t, "name", ""),
                    category=getattr(t, "category", None),
                    tags=getattr(t, "tags", None),
                    infohash=getattr(t, "infohash_v1", getattr(t, "hash", None)),
                    save_path=getattr(t, "save_path", None),
                    timestamp_finished=getattr(t, "completion_on", None),
                    session_file=None,
                    seeding_time=getattr(t, "seeding_time", None),
                    total_size=getattr(t, "total_size", None),
                )
                mapped.append(ti)

            return mapped
        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def move_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Move torrent files from NVMe to Spinning Rust after N seconds"""
        if torrent_list:
            logger.info("Searching for torrents to move...")
            
            for torrent in torrent_list:
                data_path = os.path.join(torrent.save_path or '', torrent.name)
                root_path = os.path.commonpath([data_path, config.nvme_dir])

                if (torrent.seeding_time or 0) > config.nvme_time and root_path == config.nvme_dir:
                    torrent_directory = os.path.join(config.rust_dir, torrent.category)
                    logger.info(f"Moving {torrent.name} to {torrent_directory}")

                    if not config.dry_run:
                        try:
                            self.client.torrents_set_location(location=torrent_directory, torrent_hashes=torrent.infohash)
                        except Exception as err:
                            logger.error(err)
        else:
            logger.error("List of torrents is empty!")

    def export_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Copy all torrents from qBittorrent to backup dir"""
        if torrent_list:
            export_date = datetime.now().strftime("%Y-%m-%dT%H%M%S")
            backup_path = os.path.join(config.export_dir, export_date)
            logger.info(f"Copying all .torrent files to: {backup_path}")

            for torrent in torrent_list:
                torrent_name = torrent.name
                torrent_output_path = os.path.join(backup_path, torrent.category)
                torrent_output_file = os.path.join(torrent_output_path, f"{torrent_name}.torrent")

                if not os.path.exists(torrent_output_file):
                    try:
                        if not config.dry_run:
                            make_dir(torrent_output_path)
                            torrent_file_bytes = self.client.torrents_export(torrent_hash=torrent.infohash)
                            with open(torrent_output_file, "wb") as fh:
                                fh.write(torrent_file_bytes)
                        logger.debug(f"Exported .torrent: {torrent_name}")
                    except FileNotFoundError:
                        logger.error(f"No such file or directory: '{torrent_output_file}'")
                        continue
                else:
                    logger.warning(f"Torrent Exists: {torrent_output_file}")

            if config.zip_export:
                zip_output_file = os.path.join(config.export_dir, f"qBittorrent_{export_date}.zip")
                logger.info("Creating zip archive of exported torrents...")
                create_zip(backup_path, zip_output_file)
                delete_files(backup_path)
        else:
            logger.error("List of torrents is empty!")

    def unregistered_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Delete unregistered torrents from client"""
        if torrent_list:
            torrents_to_delete = list()
            logger.info("Searching for unregistered torrents...")

            for torrent in torrent_list:
                torrent_infohash = torrent.infohash
                try:
                    torrent_tracker = self.client.torrents_trackers(torrent_hash=torrent_infohash)
                except Exception:
                    torrent_tracker = []

                unregistered = re.search("Unregistered", getattr(torrent_tracker[-1], 'msg', '') if torrent_tracker else "")
                label_allowed = False if torrent.category in config.skip_labels else True

                if unregistered and label_allowed:
                    torrents_to_delete.append(torrent_infohash)
                    logger.debug(f"Unregistered torrent found: {torrent.name}")

            if not config.dry_run and torrents_to_delete:
                try:
                    logger.info(f"Deleting {len(torrents_to_delete)} unregistered torrents from client...")
                    self.client.torrents_delete(delete_files=True, torrent_hashes=torrents_to_delete)
                except Exception as err:
                    logger.error(err)
            else:
                logger.info("No unregistered torrents found!")
        else:
            logger.error("List of torrents is empty!")

    def autoremove_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Delete torrents that have been seeding for more than N hours"""
        if torrent_list:
            torrents_to_delete = list()
            logger.info("Searching for torrents to autoremove...")

            for torrent in torrent_list:
                torrent_seed_time = (torrent.seeding_time or 0) // 3600 # hours
                torrent_category = torrent.category
                seed_time = config.category_seed_time.get(torrent_category, config.minimum_seed_time)
                
                if torrent_seed_time > seed_time and torrent_category not in config.skip_labels:
                    torrents_to_delete.append(torrent.infohash)
                    logger.debug(f"Torrent found: seed_time={torrent_seed_time} - {torrent.name} ")

            if not config.dry_run and torrents_to_delete:
                try:
                    logger.info(f"Deleting {len(torrents_to_delete)} torrents older then {config.minimum_seed_time} hours from client...")
                    self.client.torrents_delete(delete_files=True, torrent_hashes=torrents_to_delete)
                except Exception as err:
                    logger.error(err)
            else:
                logger.info("No torrents found to autoremove!")
        else:
            logger.error("List of torrents is empty!")

    def upload_torrents(self, config: SeedboxConfig, torrent_files: list) -> None:
        """Upload .torrent files to qBittorrent"""

        if torrent_files:
            for torrent_file in torrent_files:
                try:
                    self.client.torrents_add(torrent_files=torrent_file, save_path=config.torrent_save_path, category=config.torrent_label, tags=config.torrent_tag, is_paused=True)
                    logger.info(f"Uploaded torrent to qBittorrent: {os.path.basename(torrent_file)}")
                except Exception as err:
                    logger.error(err)
                    continue
        else:
            logger.error("List of .torrent files is empty!")
