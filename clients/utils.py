#
# utils.py - Shared utilities for client implementations
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
# Created - 2026-03-31
# Updated - 2026-03-31
# Version - 1.0.0
# Requires - loguru rcguy_utils
#

import os
import shutil
from datetime import datetime
from loguru import logger
from typing import List
from my_utils import make_dir, create_zip, delete_files
from models.config import SeedboxConfig
from models.torrent_info import TorrentInfo


def export_session_torrents(config: SeedboxConfig, torrent_list: List[TorrentInfo], zip_prefix: str = "export") -> None:
    """Copy torrent session files into `config.export_dir/<timestamp>/<category>` and optionally zip them.

    Args:
        config: SeedboxConfig with export settings.
        torrent_list: List of TorrentInfo objects (must include `session_file`).
        zip_prefix: Prefix to use for the created zip file (e.g., 'Deluge' or 'rTorrent').
    """
    if not torrent_list:
        logger.error("List of torrents is empty!")
        return

    export_date = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    backup_path = os.path.join(config.export_dir, export_date)
    logger.info(f"Copying all .torrent files to: {backup_path}")

    for torrent in torrent_list:
        category = torrent.category or "Uncategorized"
        torrent_output_path = os.path.join(backup_path, category)
        torrent_output_file = os.path.join(torrent_output_path, f"{torrent.name}.torrent")

        if not os.path.exists(torrent_output_file):
            try:
                if not config.dry_run and torrent.session_file and os.path.isfile(torrent.session_file):
                    make_dir(torrent_output_path)
                    shutil.copy2(torrent.session_file, torrent_output_file)
                    logger.debug(f"Exported .torrent: {torrent.name}")
            except FileNotFoundError:
                logger.error(f"No such file or directory: '{torrent.session_file}'")
                continue
        else:
            logger.warning(f"Torrent Exists: {torrent_output_file}")

    if config.zip_export:
        zip_output_file = os.path.join(config.export_dir, f"{zip_prefix}_{export_date}.zip")
        logger.info("Creating zip archive of exported torrents...")
        create_zip(backup_path, zip_output_file)
        delete_files(backup_path)
