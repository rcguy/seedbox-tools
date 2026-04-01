#
# rtorrent.py - Simple class for managing rTorrent
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
# Updated - 2026-04-01
# Version - 1.5.1
# Requires - loguru
#

"""
rTorrent client module for seedbox management.

This module provides the rTorrentClient class, which implements the TorrentClient interface
for interacting with rTorrent via XML-RPC. It supports operations like fetching torrents,
moving files, removing unregistered torrents, exporting sessions, uploading torrents,
and auto-removing torrents based on seeding time.

Example:
    client = rTorrentClient()
    client.connect(config)
    torrents = client.get_torrents(config)
"""

import os
import sys
import time
import shutil
import xmlrpc.client
import re
from loguru import logger
from datetime import datetime
from models.torrent_info import TorrentInfo
from models.config import SeedboxConfig
from clients.base import TorrentClient
from clients.utils import export_session_torrents, make_dir, delete_files

class rTorrentClient(TorrentClient):
    """Class wrapper for rTorrent XML-RPC operations implementing TorrentClient."""

    def __init__(self) -> None:
        self.server_url = None

    def connect(self, config: SeedboxConfig) -> None:
        """Initialize the rTorrent client connection URL from configuration.

        Args:
            config: SeedboxConfig containing rtorrent.server_url.

        Returns:
            None
        """

        self.server_url = config.rtorrent.server_url

    def get_torrents(self, config: SeedboxConfig) -> list:
        """Fetch torrents from rTorrent via XML-RPC and map them to TorrentInfo objects.

        Args:
            config: SeedboxConfig containing label filter and status settings.

        Returns:
            A list of TorrentInfo objects.

        Raises:
            Exception: on XML-RPC errors (inherited from xmlrpc.client operations).
        """

        fields = ("d.name=", "d.custom1=", "d.hash=", "d.data_path=", "d.timestamp.finished=", "d.message=", "d.session_file=", "d.size_bytes=")

        try:
            logger.info("Getting list of all torrents...")
            with xmlrpc.client.ServerProxy(self.server_url) as rtorrent:
                if config.torrent_label is not None:
                    raw = rtorrent.d.multicall.filtered("", config.torrent_status, f'equal=d.custom1=,cat={config.torrent_label}', *fields)
                else:
                    raw = rtorrent.d.multicall2("", config.torrent_status, *fields)

                mapped = []
                for t in raw:
                    seeding_time = (int(time.time()) - t[4]) if t[4] else 0

                    ti = TorrentInfo(
                        name=t[0],
                        category=t[1],
                        infohash=t[2],
                        save_path=t[3],
                        timestamp_finished=t[4],
                        tracker_status=t[5],
                        session_file=t[6],
                        total_size=t[7],
                        seeding_time=seeding_time,
                    )
                    mapped.append(ti)

                logger.info(f"Found {len(mapped)} torrents")
                return mapped
        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def move_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Move torrents from NVMe staging to final rust storage based on seeding time.

        Args:
            config: SeedboxConfig containing nvme_dir, rust_dir, nvme_time, sleep_time, dry_run.
            torrent_list: list of TorrentInfo objects to evaluate and move.

        Returns:
            None

        Side effects:
            May copy files/directories, edit rTorrent session, and delete source files.
        """

        if torrent_list:
            logger.debug("Searching for torrents to move...")
            with xmlrpc.client.ServerProxy(self.server_url) as rtorrent:
                for torrent in torrent_list:
                    root_path = os.path.commonpath([torrent.save_path, config.nvme_dir])
                    
                    if torrent.seeding_time > config.nvme_time and root_path == config.nvme_dir:
                        torrent_rel_path = os.path.relpath(torrent.save_path, config.nvme_dir)
                        torrent_move_path = os.path.join(config.rust_dir, torrent_rel_path)
                        torrent_directory = os.path.dirname(torrent_move_path)
                        logger.debug(f"{torrent_rel_path} - {torrent_move_path} - {torrent_directory}")

                        if not config.dry_run:
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
                            
                            if config.sleep_time > 0:
                                logger.info(f"Sleeping for {config.sleep_time} seconds before moving next torrent...")
                                time.sleep(config.sleep_time)
        else:
            logger.error(f"List of torrents is empty!")

    def unregistered_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Remove torrents marked as unregistered, except skipped labels, and delete their data.

        Args:
            config: SeedboxConfig with skip_labels and dry_run settings.
            torrent_list: list of TorrentInfo objects to inspect.

        Returns:
            None

        Side effects:
            May stop/close/erase torrents in rTorrent and remove files from disk.
        """

        if torrent_list:
            logger.info("Searching for unregistered torrents...")
            unregistered_count = 0
            
            try:
                with xmlrpc.client.ServerProxy(self.server_url) as rtorrent:
                    for torrent in torrent_list:
                        unregistered = re.search("Unregistered", torrent.tracker_status or "", re.IGNORECASE)
    
                        if unregistered and torrent.category not in config.skip_labels:
                            unregistered_count += 1
                            logger.debug(f"Unregistered torrent found: {torrent.name} tracker_status='{torrent.tracker_status}' path={os.path.dirname(torrent.save_path)} label='{torrent.category}'")
                            if not config.dry_run:
                                multicall = xmlrpc.client.MultiCall(rtorrent)
                                multicall.d.try_stop(torrent.infohash)
                                multicall.d.try_close(torrent.infohash)
                                multicall.d.erase(torrent.infohash)
                                multicall()

                                delete_files(torrent.save_path)

                    logger.info(f"Found {unregistered_count} unregistered torrents")
                    if unregistered_count > 0 and not config.dry_run:
                        logger.debug("Saving rTorrent session...")
                        rtorrent.session.save()

            except Exception as err:
                logger.error(err)
                sys.exit(1)
        
        else:
            logger.error("List of torrents is empty!")

    def export_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Export torrent session files and optionally archive them.

        Args:
            config: SeedboxConfig with export_dir and zip_export flags.
            torrent_list: list of TorrentInfo objects representing torrents to export.

        Returns:
            None
        """

        export_session_torrents(config, torrent_list, zip_prefix="rTorrent")

    def upload_torrents(self, config: SeedboxConfig, torrent_files: list) -> None:
        """Upload .torrent files to rTorrent, setting save path and label.

        Args:
            config: SeedboxConfig with torrent_save_path and torrent_label.
            torrent_files: list of paths to .torrent files.

        Returns:
            None
        """
        
        logger.debug("Uploading torrents...")
        try:
            with xmlrpc.client.ServerProxy(self.server_url) as rtorrent:
                make_dir(config.torrent_save_path)
                for torrent in torrent_files:
                    with open(torrent, "rb") as fh:
                        rtorrent.load.raw_verbose("", xmlrpc.client.Binary(fh.read()), "d.delete_tied=", f"d.custom1.set={config.torrent_label}", f"d.directory.set={config.torrent_save_path}")
                        logger.info(f"Uploaded torrent: name='{os.path.basename(torrent)}' save_path='{config.torrent_save_path}' label='{config.torrent_label}'")
                        time.sleep(0.25)

                logger.debug(f"Uploaded {len(torrent_files)} .torrent files")

        except Exception as err:
            logger.error(err)
            sys.exit(1)

    def autoremove_torrents(self, config: SeedboxConfig, torrent_list: list) -> None:
        """Remove torrents that exceeded configured seed time from rTorrent and disk.

        Args:
            config: SeedboxConfig with category_seed_time, minimum_seed_time, skip_labels, dry_run.
            torrent_list: list of TorrentInfo objects to evaluate.

        Returns:
            None
        """

        if torrent_list:
            logger.info("Searching for torrents to autoremove...")

            try:
                with xmlrpc.client.ServerProxy(self.server_url) as rtorrent:
                    for torrent in torrent_list:
                        torrent_seeding_time = (torrent.seeding_time or 0) // 3600
                        torrent_min_seed_time = config.category_seed_time.get(torrent.category, config.minimum_seed_time)
                
                        if torrent_seeding_time > torrent_min_seed_time and torrent.category not in config.skip_labels:
                            logger.debug(f"Torrent found: seeding_time={torrent_seeding_time} - {torrent.name}")

                        if not config.dry_run:
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
