#
# deluge.py - Simple class for managing Deluge torrents
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
# Version - 1.4.0
# Requires - loguru pyyaml deluge_web_client
#

import os
import sys
import time
import shutil
import hashlib
import getpass
import re
import json
from datetime import datetime
from deluge_web_client import DelugeWebClient, TorrentOptions
from loguru import logger
from my_utils import make_dir, delete_files, create_zip
from models.torrent_info import TorrentInfo
from models.config import SeedboxConfig
from clients.base import TorrentClient
from clients.utils import export_session_torrents


class DelugeClient(TorrentClient):
    """Class wrapper around DelugeWebClient implementing TorrentClient interface."""

    def __init__(self) -> None:
        self.client = None

    def connect(self, config: SeedboxConfig):
        try:
            logger.info("Connecting to Deluge WebUI...")
            self.client = DelugeWebClient(**config.deluge.conn_info)
        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def load_web_cfg(self, config_file: str) -> tuple:
        try:
            file_path = os.path.abspath(config_file)
            logger.info(f"Loading webui config from {file_path}")
            with open(file_path, 'r') as f:
                content = f.read()

            depth = 0
            first_dict_end = 0
            for i, char in enumerate(content):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        first_dict_end = i + 1
                        break

            dict1_str = content[:first_dict_end]
            dict2_str = content[first_dict_end:]

            dict1 = json.loads(dict1_str)
            dict2 = json.loads(dict2_str)

            return dict1, dict2

        except FileNotFoundError:
            logger.error(f"Config file could not be found: '{os.path.basename(file_path)}'")
            sys.exit(1)
        except PermissionError:
            logger.error(f"Permission denied: '{os.path.basename(file_path)}'")
            sys.exit(1)
        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def save_web_cfg(self, config_file: str, dict1, dict2) -> None:
        try:
            file_path = os.path.abspath(config_file)
            logger.info(f"Saving webui config to {file_path}")
            with open(file_path, 'w') as f:
                f.write(json.dumps(dict1, indent=4) + json.dumps(dict2, indent=4))
        except FileNotFoundError:
            logger.error(f"Config file could not be found: '{os.path.basename(file_path)}'")
            sys.exit(1)
        except PermissionError:
            logger.error(f"Permission denied: '{os.path.basename(file_path)}'")
            sys.exit(1)
        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def reset_web_password(self, config: SeedboxConfig) -> None:
        """Reset Deluge WebUI password by editing the web.conf file."""
        try:
            logger.info("Resetting Deluge WebUI password...")
            cfg1, cfg2 = self.load_web_cfg(config.deluge.web_cfg_path)
            salt = cfg2['pwd_salt']
            logger.debug(f"Old password hash: {cfg2['pwd_sha1']}")

            pw_hash = hashlib.sha1()
            pw_hash.update(salt.encode())

            while True:
                password = getpass.getpass('Enter new password: ')
                second = getpass.getpass('Re-enter new password: ')
                if password == second:
                    break
                else:
                    print("Passwords do not match. Please try again.")

            pw_hash.update(password.encode())
            cfg2['pwd_sha1'] = pw_hash.hexdigest()
            logger.debug(f"New password hash: {cfg2['pwd_sha1']}")

            if not config.dry_run:
                self.save_web_cfg(config.deluge.web_cfg_path, cfg1, cfg2)
                logger.success("Password reset successfully!")

        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def get_torrents(self, config: SeedboxConfig) -> list:
        """Get list of all torrents in the client and return a list of TorrentInfo"""
        try:
            logger.info("Getting list of all torrents...")
            raw = self.client.get_torrents_status(keys=('hash', 'name', 'save_path', 'seeding_time', 'completed_time', 'state', 'tracker_status', 'label', 'total_size'), 
                                                 filter_dict=config.filter_dict, timeout=60).result

            mapped = []
            for tid, info in raw.items():
                ti = TorrentInfo(
                    name=info.get('name'),
                    category=info.get('label'),
                    infohash=info.get('hash'),
                    save_path=info.get('save_path'),
                    timestamp_finished=info.get('completed_time'),
                    state=info.get('state'),
                    tracker_status=info.get('tracker_status'),
                    session_file=os.path.join(config.deluge.state_dir, f"{tid}.torrent") if config.deluge and config.deluge.state_dir else None,
                    seeding_time=info.get('seeding_time'),
                    total_size=info.get('total_size'),
                )
                mapped.append(ti)

            logger.success(f"Found {len(mapped)} torrents")
            return mapped
        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def move_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Move torrent files from NVMe to Spinning Rust after N seconds"""
        if torrent_list:
            logger.info("Searching for torrents to move...")

            for torrent in torrent_list:
                root_path = os.path.commonpath([torrent.save_path, config.nvme_dir])

                if torrent.state == 'Seeding' and (torrent.seeding_time or 0) > config.nvme_time and root_path == config.nvme_dir:
                    torrent_directory = os.path.join(config.rust_dir, torrent.category)
                    logger.info(f"Moving {torrent.name} to {torrent_directory}")

                    if not config.dry_run:
                        payload = {"method": "core.move_storage",
                                    "params": [[torrent.tid], torrent_directory],
                                }
                        moved = self.client.execute_call(payload)

                        if moved.error is not None:
                            logger.error(f"Failed to move torrent: {torrent.name} - {moved.message}")
                            continue

                        if config.sleep_time > 0:
                            logger.info(f"Sleeping for {config.sleep_time} seconds before moving next torrent...")
                            time.sleep(config.sleep_time)
        else:
            logger.error("List of torrents is empty!")

    def export_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Copy all torrents from client to backup dir (delegates to clients.utils)."""

        export_session_torrents(config, torrent_list, zip_prefix="Deluge")

    def unregistered_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Delete unregistered torrents from client"""
        if torrent_list:
            torrents_to_delete = list()
            logger.info("Searching for unregistered torrents...")

            for torrent in torrent_list:
                torrent_label = torrent.category
                torrent_tracker = torrent.tracker_status
                unregistered = re.search("Unregistered", torrent_tracker or "", re.IGNORECASE)
                label_allowed = False if torrent_label in config.skip_labels else True

                if unregistered and label_allowed:
                    torrents_to_delete.append(torrent.tid)
                    logger.debug(f"Unregistered torrent found: {torrent.name} tracker_status='{torrent_tracker}' path={torrent.save_path} label='{torrent_label}'")

            if not config.dry_run and torrents_to_delete:
                try:
                    logger.info(f"Deleting {len(torrents_to_delete)} unregistered torrents from client...")
                    removed = self.client.remove_torrents(torrents_to_delete, remove_data=True)
                    if removed.error is not None:
                        logger.error("Failed to remove torrents!")
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
                    torrents_to_delete.append(torrent.tid)
                    logger.debug(f"Torrent found: seed_time={torrent_seed_time} - {torrent.name}")

            if not config.dry_run and torrents_to_delete:
                try:
                    logger.info(f"Deleting {len(torrents_to_delete)} torrents older then {config.minimum_seed_time} hours from client...")
                    removed = self.client.remove_torrents(torrents_to_delete, remove_data=True)
                    if removed.error is not None:
                        logger.error("Failed to remove torrents!")
                except Exception as err:
                    logger.error(err)
            else:
                logger.info("No torrents found to autoremove!")
        else:
            logger.error("List of torrents is empty!")

    def upload_torrents(self, config: SeedboxConfig, torrent_files: list) -> None:
        """Upload .torrent files to client with save path and label"""

        torrent_options = TorrentOptions(
                add_paused=True,
                label=config.torrent_label,
                download_location=config.torrent_save_path,
            )
        
        if torrent_files:
            try:
                uploads = self.client.upload_torrents(torrent_files, torrent_options)
                for k, v in uploads.items():
                    if v.message == 'Torrent already exists':
                        logger.error(f"Torrent already exists in client! - '{k}'")
                    elif v.error is not None:
                        logger.error(f"Failed to upload torrent: '{k}' - {v.message}")
                    else:
                        logger.debug(f"Uploaded torrent: '{k}' save_path='{config.torrent_save_path}' label='{config.torrent_label}'")
            except Exception as err:
                logger.error(err)
        else:
            logger.error("List of .torrent files is empty!")    
