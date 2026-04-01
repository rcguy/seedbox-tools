#!/home/rcguy/python-projects/seedbox/venv/bin/python3
# -*- coding: utf-8 -*-

#
# deluge.py - Simple functions for managing Deluge torrents
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
# Version - 1.3.1
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
from deluge_web_client import DelugeWebClient, TorrentOptions, Response
from loguru import logger
from my_utils import make_dir
from models.torrent_info import TorrentInfo


def load_web_cfg(config_file: str) -> tuple:
    """
    Load and parse two JSON-encoded dicts from a cfg file.
    
    Args:
        config_file (str): Path to the cfg file
        
    Returns:
        tuple: (dict1, dict2) - The two parsed dictionaries
    """

    try:
        file_path = os.path.abspath(config_file)
        logger.info(f"Loading webui config from {file_path}")
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Find the boundary between the two dicts by tracking brace depth
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
        
        # Split and parse both dicts
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


def save_web_cfg(config_file: str, dict1, dict2) -> None:
    """
    Save two dictionaries back to a cfg file as concatenated JSON.
    
    Args:
        config_file (str): Path to the cfg file
        dict1 (dict): First dictionary
        dict2 (dict): Second dictionary
    """

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


def reset_web_password(web_cfg_path: str) -> None:
    """Reset Deluge WebUI password by editing the web.conf file"""

    try:
        logger.info("Resetting Deluge WebUI password...")
        config1, config2 = load_web_cfg(web_cfg_path)
        salt = config2['pwd_salt']
        logger.debug(f"Old password hash: {config2['pwd_sha1']}")

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
        config2['pwd_sha1'] = pw_hash.hexdigest()
        logger.debug(f"New password hash: {config2['pwd_sha1']}")
        #print(json.dumps(config1, indent=4) + json.dumps(config2, indent=4))

        if not dry_run:
            save_web_cfg(web_cfg_path, config1, config2)
            logger.success("Password reset successfully!")

    except Exception as err:
        logger.error(err)
        sys.exit(1)


def get_torrents(client: DelugeWebClient, filter: dict = {}) -> list:
    """Get list of all torrents in the client and return a list of TorrentInfo"""

    try:
        logger.info("Getting list of all torrents...")
        raw = client.get_torrents_status(keys=('hash', 'name', 'save_path', 'seeding_time', 'completed_time', 'state', 'tracker_status', 'label', 'total_size'), 
                                         filter_dict=filter, timeout=60).result

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
                session_file=os.path.join(state_dir, f"{tid}.torrent") if 'state_dir' in globals() else None,
                seeding_time=info.get('seeding_time'),
                total_size=info.get('total_size'),
            )
            mapped.append(ti)

        logger.success(f"Found {len(mapped)} torrents")
        return mapped
    except Exception as err:
        logger.error(err)
        sys.exit(1)


def move_torrents(client: DelugeWebClient, torrent_list: list) -> None:
    """Move torrent files from NVMe to Spinning Rust after N seconds"""

    if torrent_list:
        logger.info("Searching for torrents to move...")

        for torrent in torrent_list:
            root_path = os.path.commonpath([torrent.save_path, nvme_dir])

            if torrent.state == 'Seeding' and (torrent.seeding_time or 0) > nvme_time and root_path == nvme_dir:
                torrent_directory = os.path.join(rust_dir, torrent.category)
                logger.info(f"Moving {torrent.name} to {torrent_directory}")

                if not dry_run:
                    payload = {"method": "core.move_storage",
                                "params": [[torrent.tid], torrent_directory],
                            }
                    moved = client.execute_call(payload)

                    if moved.error is not None:
                        logger.error(f"Failed to move torrent: {torrent.name} - {moved.message}")
                        continue

                    if sleep_time > 0:
                        logger.info(f"Sleeping for {sleep_time} seconds before moving next torrent...")
                        time.sleep(sleep_time)
    else:
        logger.error("List of torrents is empty!")


def export_torrents(backup_dir: str, torrent_list: list) -> None:
    """Copy all torrents from client to backup dir"""

    if torrent_list:
        logger.info(f"Copying all .torrent files to: {backup_dir}")
        export_date = datetime.now().strftime("%Y-%m-%dT%H%M%S")

        for torrent in torrent_list:
            torrent_name = torrent.name
            torrent_output_path = os.path.join(backup_dir, export_date, torrent.category)
            torrent_output_file = os.path.join(torrent_output_path, f"{torrent_name}.torrent")
            torrent_input_file = torrent.session_file

            if not os.path.exists(torrent_output_file):
                try:
                    if not dry_run and torrent_input_file and os.path.isfile(torrent_input_file):
                        make_dir(torrent_output_path)
                        shutil.copy2(torrent_input_file, torrent_output_file)
                    logger.debug(f"Exported .torrent: {torrent_name}")
                except FileNotFoundError:
                    logger.error(f"No such file or directory: '{torrent_output_file}'")
                    continue
            else:
                logger.warning(f"Torrent Exists: {torrent_output_file}")

        logger.success(f"Exported {len(torrent_list)} .torrent files to {backup_dir}!")
    else:
        logger.error("List of torrents is empty!")


def unregistered_torrents(client: DelugeWebClient, torrent_list: list) -> None:
    """Delete unregistered torrents from client"""

    if torrent_list:
        torrents_to_delete = list()
        logger.info("Searching for unregistered torrents...")

        for torrent in torrent_list:
            torrent_label = torrent.category
            torrent_tracker = torrent.tracker_status
            unregistered = re.search("Unregistered", torrent_tracker or "", re.IGNORECASE)
            label_allowed = False if torrent_label in skip_labels else True

            if unregistered and label_allowed:
                torrents_to_delete.append(torrent.tid)
                logger.debug(f"Unregistered torrent found: {torrent.name} tracker_status='{torrent_tracker}' path={torrent.save_path} label='{torrent_label}'")

        if not dry_run and torrents_to_delete:
            try:
                logger.info(f"Deleting {len(torrents_to_delete)} unregistered torrents from client...")
                removed = client.remove_torrents(torrents_to_delete, remove_data=True)
                if removed.error is not None:
                    logger.error("Failed to remove torrents!")
            except Exception as err:
                logger.error(err)
        else:
            logger.info("No unregistered torrents found!")
    else:
        logger.error("List of torrents is empty!")


def autoremove_torrents(client: DelugeWebClient, torrent_list: list) -> None:
    """Delete torrents that have been seeding for more than N hours"""

    if torrent_list:
        torrents_to_delete = list()
        logger.info("Searching for torrents to autoremove...")

        for torrent in torrent_list:
            torrent_seed_time = (torrent.seeding_time or 0) // 3600 # hours
            torrent_category = torrent.category
            seed_time = category_seed_time.get(torrent_category, minimum_seed_time)
            
            if torrent_seed_time > seed_time and torrent_category not in skip_labels:
                torrents_to_delete.append(torrent.tid)
                logger.debug(f"Torrent found: seed_time={torrent_seed_time} - {torrent.name}")

        if not dry_run and torrents_to_delete:
            try:
                logger.info(f"Deleting {len(torrents_to_delete)} torrents older then {minimum_seed_time} hours from client...")
                removed = client.remove_torrents(torrents_to_delete, remove_data=True)
                if removed.error is not None:
                    logger.error("Failed to remove torrents!")
            except Exception as err:
                logger.error(err)
        else:
            logger.info("No torrents found to autoremove!")
    else:
        logger.error("List of torrents is empty!")


def upload_torrents(client: DelugeWebClient, torrent_files: list, save_path: str, label: str, paused: bool = True) -> None:
    """Upload .torrent files to client with save path and label"""

    torrent_options = TorrentOptions(
            add_paused=paused,
            label=label,
            download_location=save_path,
        )
    
    if torrent_files:
        try:
            uploads = client.upload_torrents(torrent_files, torrent_options)
            for k, v in uploads.items():
                if v.message == 'Torrent already exists':
                    logger.error(f"Torrent already exists in client! - '{k}'")
                elif v.error is not None:
                    logger.error(f"Failed to upload torrent: '{k}' - {v.message}")
                else:
                    logger.debug(f"Uploaded torrent: '{k}' save_path='{save_path}' label='{label}'")
        except Exception as err:
            logger.error(err)
    else:
        logger.error("List of .torrent files is empty!")
