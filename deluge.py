#!/home/rcguy/python-projects/seedbox/venv/bin/python3
# -*- coding: utf-8 -*-

#
# deluge_tools.py - Simple tools for managing Deluge torrents
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
# Updated - 2026-03-29
# Version - 1.2.2
# Requires - loguru pyyaml deluge_web_client
#

import os
import sys
import time
import shutil
import argparse
import hashlib
import getpass
import re
import yaml
import json
from datetime import datetime
from deluge_web_client import DelugeWebClient, TorrentOptions, Response
from loguru import logger
from my_utils import make_dir, load_yaml


def cli() -> object:
    """Command Line Interface"""

    # https://stackoverflow.com/a/44333798
    formatter = lambda prog: argparse.HelpFormatter(prog, width=256, max_help_position=64)

    parser = argparse.ArgumentParser(description="Deluge Python Tools", formatter_class=formatter)
    
    parser.add_argument("-c", "--config",
                        type=str,
                        default=None,
                        help="config file path")
    
    parser.add_argument("-d", "--export-dir",
                        type=str,
                        default=None,
                        help="export .torrent files to this directory")

    parser.add_argument("-l", "--label",
                        type=str,
                        default=None,
                        help="label for adding torrents to client (see --torrents-add)")

    parser.add_argument("-p", "--path",
                        type=str,
                        default=None,
                        help="save path for adding torrents to client (see --torrents-add)")
    
    parser.add_argument("-f", "--filter",
                        type=str,
                        nargs="+",
                        default=None,
                        help="filter torrents by key=value pairs (e.g. --filter label=Movies)")

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

    parser.add_argument("-v", "--log-level",
                        type=str,
                        default="INFO",
                        metavar="LOG_LEVEL",
                        choices=["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"],
                        help="set log level (default: INFO)")

    commands = parser.add_argument_group('commands')

    commands.add_argument("-T", "--add-torrents",
                        type=str,
                        nargs="+",
                        default=None,
                        metavar="FILES",
                        help="add .torrent files to client with this save path and label (see --label and --path)")
    
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

    commands.add_argument("-R", "--reset-password",
                        action="store_true",
                        help="reset Deluge WebUI password by editing the web.conf file")

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit()

    return parser.parse_args()


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


def get_torrents(client: DelugeWebClient, filter: dict = {}) -> dict:
    """Get list of all torrents in the client"""

    all_torrents = dict()

    try:
        logger.info("Getting list of all torrents...")
        all_torrents = client.get_torrents_status(keys=('hash', 'name', 'save_path', 'seeding_time', 'state', 'tracker_status', 'label'), 
                                                    filter_dict=filter, timeout=60).result
        logger.success(f"Found {len(all_torrents)} torrents")
        return all_torrents
    except Exception as err:
        logger.error(err)
        sys.exit(1)


def list_torrents(torrent_list: dict) -> None:
    """Print list of torrents in client"""

    if torrent_list:
        for k, v in torrent_list.items():
            logger.debug(f"{k[-6:]}: {v['name']} path={v['save_path']} seed_time={v['seeding_time']} state={v['state']} tracker_status='{v['tracker_status']}' label='{v['label']}'")
    else:
        logger.error("List of torrents is empty!")


def move_torrents(client: DelugeWebClient, torrent_list: dict) -> None:
    """Move torrent files from NVMe to Spinning Rust after N seconds"""

    if torrent_list:
        logger.info("Searching for torrents to move...")

        for tid, info in torrent_list.items():
            #data_path = os.path.join(info['save_path'], info['name'])
            root_path = os.path.commonpath([info['save_path'], nvme_dir])

            if info['state'] == 'Seeding' and info['seeding_time'] > nvme_time and root_path == nvme_dir:
                torrent_directory = os.path.join(rust_dir, info['label'])
                logger.info(f"Moving {info['name']} to {torrent_directory}")

                if not dry_run:
                    payload = {"method": "core.move_storage",
                                "params": [[tid], torrent_directory],
                            }
                    moved = client.execute_call(payload)

                    if moved.error is not None:
                        logger.error(f"Failed to move torrent: {info['name']} - {moved.message}")
                        continue

                    if sleep_time > 0:
                        logger.info(f"Sleeping for {sleep_time} seconds before moving next torrent...")
                        time.sleep(sleep_time)
    else:
        logger.error("List of torrents is empty!")


def export_torrents(backup_dir: str, torrent_list: dict) -> None:
    """Copy all torrents from client to backup dir"""

    if torrent_list:
        logger.info(f"Copying all .torrent files to: {backup_dir}")
        export_date = datetime.now().strftime("%Y-%m-%dT%H%M%S")

        for tid, info in torrent_list.items():
            torrent_name = info['name']
            torrent_output_path = os.path.join(backup_dir, export_date, info['label'])
            torrent_output_file = os.path.join(torrent_output_path, f"{torrent_name}.torrent")
            torrent_input_file = os.path.join(state_dir, f"{tid}.torrent")

            if not os.path.exists(torrent_output_file):
                try:
                    if not dry_run and os.path.isfile(torrent_input_file):
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


def unregistered_torrents(client: DelugeWebClient, torrent_list: dict) -> None:
    """Delete unregistered torrents from client"""

    if torrent_list:
        torrents_to_delete = list()
        logger.info("Searching for unregistered torrents...")

        for tid, info in torrent_list.items():
            torrent_label = info['label']
            torrent_tracker = info['tracker_status']
            unregistered = re.search("Unregistered", torrent_tracker, re.IGNORECASE)
            label_allowed = False if torrent_label in skip_labels else True

            if unregistered and label_allowed:
                torrents_to_delete.append(tid)
                logger.debug(f"Unregistered torrent found: {info['name']} tracker_status='{torrent_tracker}' path={info['save_path']} label='{info['label']}'")

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


def autoremove_torrents(client: DelugeWebClient, torrent_list: dict) -> None:
    """Delete torrents that have been seeding for more than N hours"""

    if torrent_list:
        torrents_to_delete = list()
        logger.info("Searching for torrents to autoremove...")

        for tid, info in torrent_list.items():
            torrent_seed_time = info['seeding_time'] // 3600 # hours
            torrent_category = info['label']
            seed_time = category_seed_time.get(torrent_category, minimum_seed_time)
            
            if torrent_seed_time > seed_time and torrent_category not in skip_labels:
                torrents_to_delete.append(tid)
                logger.debug(f"Torrent found: seed_time={torrent_seed_time} - {info['name']}")

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


def main():
    """Main function"""

    global dry_run, skip_labels, sleep_time, category_seed_time, minimum_seed_time, nvme_time, nvme_dir, rust_dir, deluge_dir, state_dir

    script_cwd = os.path.dirname(os.path.abspath(__file__))
    logger.add(os.path.join(script_cwd, "logs/deluge_tools.log"),
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
    deluge_dir = cfg["Deluge"]["cfg_dir"]
    state_dir = os.path.join(deluge_dir, "state")
    web_cfg_path = os.path.join(deluge_dir, "web.conf")
    filter_dict = dict(map(lambda s: s.split('='), args.filter)) if args.filter else {}
    export_dir = os.path.abspath(args.export_dir) if args.export_dir else os.path.join(script_cwd, cfg["export_dir"])
    conn_info = dict(
        url=cfg["Deluge"]["url"],
        password=cfg["Deluge"]["password"],
    )

    try:
        
        if args.reset_password:
            reset_web_password(web_cfg_path)
            sys.exit()

        logger.info("Logging into Deluge Client...")
        with DelugeWebClient(**conn_info) as client:

            if args.add_torrents:
                upload_torrents(client, args.add_torrents, args.path, args.label, paused=True)
                sys.exit()
            
            all_torrents = get_torrents(client, filter_dict)

            if args.list_torrents:
                list_torrents(all_torrents)
            if args.unregistered:
                unregistered_torrents(client, all_torrents)  
            if args.move_torrents:
                move_torrents(client, all_torrents)
            if args.autoremove:
                autoremove_torrents(client, all_torrents)
            if args.export_torrents:
                export_torrents(export_dir, all_torrents)

    except Exception as err:
        logger.error(err)
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
