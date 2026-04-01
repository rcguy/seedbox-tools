#!/home/rcguy/python-projects/seedbox/venv/bin/python3
# -*- coding: utf-8 -*-

#
# seedbox_tools.py - Simple tools for managing Deluge, qBittorrent and rTorrent
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
# Requires - loguru pyyaml rich rcguy_utils qbittorrent-api deluge_web_client
#

import os
import sys
import argparse
import importlib
from loguru import logger
from rich.console import Console
from rich.table import Table
from my_utils import find_files
from models.config import load_config
from clients.rtorrent import rTorrentClient
from clients.deluge import DelugeClient
from clients.qbittorrent import qBittorrentClient

CLIENT_MAP = {
    "rtorrent": rTorrentClient,
    "deluge": DelugeClient,
    "qbittorrent": qBittorrentClient,
}


def cli() -> object:
    """Command Line Interface"""

    # https://stackoverflow.com/a/44333798
    formatter = lambda prog: argparse.HelpFormatter(prog, width=256, max_help_position=96)

    parser = argparse.ArgumentParser(description="Seedbox Python Tools", formatter_class=formatter)

    parser.add_argument("-c", "--client",
                        type=str,
                        default="rtorrent",
                        metavar="CLIENT",
                        choices=["rtorrent", "qbittorrent", "deluge"],
                        help="torrent client to manage (default: rtorrent)")

    parser.add_argument("-C", "--config",
                        type=str,
                        default=None,
                        help="config file path")

    parser.add_argument("-v", "--log-level",
                        type=str,
                        default="INFO",
                        metavar="LOG_LEVEL",
                        choices=["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"],
                        help="set log level (default: INFO)")

    parser.add_argument("-p", "--path",
                        type=str,
                        default=None,
                        help="save path for adding torrents to client (see --add-torrents)")

    parser.add_argument("-l", "--label",
                        type=str,
                        default=None,
                        help="label for filtering or adding torrents to client (see --add-torrents)")

    parser.add_argument("-k", "--skip-labels",
                        type=str,
                        nargs="+",
                        default=None,
                        metavar="LABELS",
                        help="skip torrents with these labels when performing commands")

    parser.add_argument("-s", "--status",
                        type=str,
                        default="seeding",
                        metavar="STATUS",
                        choices=["main", "default", "active", "started", "stopped", "complete", "incomplete", "hashing", "seeding", "leeching", "rat_0", "rat_1", "rat_2", "rat_3", "rat_4", "rat_5", "rat_6", "rat_7"],
                        help="filter torrents by status")
    
    parser.add_argument("-S", "--seed-time",
                        type=int,
                        default=None,
                        help="minimum seed time in hours before removing torrents from client")
    
    parser.add_argument("-n", "--nvme-time",
                        type=int,
                        default=None,
                        help="minimum time in seconds that torrent has been on NVMe before moving to Spinning Rust")

    parser.add_argument("-e", "--export-dir",
                        type=str,
                        default=None,
                        help="export .torrent files to this directory")

    parser.add_argument("-z", "--zip",
                        action="store_true",
                        help="create zip archive of exported torrents")

    parser.add_argument("-d", "--dry-run",
                        action="store_true",
                        help="perform a trial run with no changes made")

    commands = parser.add_argument_group('Commands')

    commands.add_argument("-A", "--add",
                        type=str,
                        default="",
                        metavar="FILES",
                        help="add .torrent files to client with this save path and label (see --label and --path)")
    
    commands.add_argument("-R", "--remove",
                        action='store_true',
                        help="remove torrents that have been seeding for more than N hours (see --seed-time)")
    
    commands.add_argument("-U", "--unregistered",
                        action='store_true',
                        help='remove unregistered torrents from client')

    commands.add_argument("-L", "--list",
                        action="store_true",
                        help="list all torrents in client")

    commands.add_argument("-M", "--move",
                        action="store_true",
                        help="move torrents from NVMe to Spinning Rust after N seconds (see --nvme-time)")
    
    commands.add_argument("-E", "--export",
                        action="store_true",
                        help="export all .torrent files from client")

    summary = parser.add_argument_group('Summary')

    summary.add_argument("--summary",
                        action="store_true",
                        help="print category summary table with count and total size of torrents in each category")

    summary.add_argument("--summary-sort",
                        nargs="+",
                        metavar=("COLUMN", "ORDER"),
                        type=str,
                        default=["category", "asc"],
                        help="column and order to sort category summary by (e.g. 'size desc' or 'count asc')")

    Deluge = parser.add_argument_group('Deluge')

    Deluge.add_argument("-f", "--filter",
                        type=str,
                        nargs="+",
                        default=None,
                        help="filter torrents by key=value pairs (e.g. --filter label=Movies)")

    Deluge.add_argument("--reset-password",
                        action="store_true",
                        help="reset Deluge WebUI password by editing the web.conf file")

    qBittorrent = parser.add_argument_group('qBittorrent')

    qBittorrent.add_argument("-t", "--tag",
                        type=str,
                        default=None,
                        help="filter torrents by tag or add this tag to torrents when adding to client (see --add-torrents)")

    #rTorrent = parser.add_argument_group('rTorrent')

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit()

    return parser.parse_args()


def list_torrents(torrent_list: list) -> None:
    """Print list of torrents in client"""

    if torrent_list:
        for torrent in torrent_list:
            #seeding_hours = (torrent.seeding_time // 3600) if torrent.seeding_time else None
            logger.debug(f"{(torrent.infohash or '')[-6:]}: {torrent.name} label='{torrent.category}' seed_time={torrent.seeding_time} path={torrent.save_path} session_file={torrent.session_file} tracker_status='{torrent.tracker_status}'")
    else:
        logger.error("List of torrents is empty!")


def print_summary(torrent_list: list, sort_by: str = "category", descending: bool = False) -> None:
    """Print category summary table (count + total size) using rich."""

    if not torrent_list:
        logger.warning("No torrents to summarize")
        return

    if sort_by not in ["category", "count", "size"]:
        logger.warning(f"Invalid sort_by: '{sort_by}', falling back to 'category'")
        sort_by = "category"

    def _format_bytes(num_bytes: int) -> str:
        if num_bytes is None:
            return "0 B"
        try:
            num = float(num_bytes)
        except (TypeError, ValueError):
            return "0 B"

        for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
            if num < 1024.0:
                return f"{num:,.2f} {unit}"
            num /= 1024.0
        return f"{num:,.2f} EB"

    category_data = {}

    for torrent in torrent_list:
        category = torrent.category or "Uncategorized"
        stats = category_data.setdefault(category, {"count": 0, "size": 0})
        stats["count"] += 1

        if torrent.total_size is not None:
            try:
                stats["size"] += int(torrent.total_size)
            except (TypeError, ValueError):
                logger.debug(f"Invalid size for torrent {torrent.name!r}: {torrent.total_size}")

    table = Table(title="Torrent Summary", show_lines=False)
    table.add_column("Category", style="cyan", no_wrap=True)
    table.add_column("Torrents", style="magenta", justify="right")
    table.add_column("Total Size", style="green", justify="right")

    if sort_by == "category":
        ordered = sorted(category_data.items(), key=lambda kv: kv[0].lower(), reverse=descending)
    else:
        ordered = sorted(category_data.items(), key=lambda kv: kv[1][sort_by], reverse=descending)

    total_count = 0
    total_size = 0

    for category, stats in ordered:
        total_count += stats["count"]
        total_size += stats["size"]

        table.add_row(
            category,
            str(stats["count"]),
            _format_bytes(stats["size"]),
        )

    # Add a footer row with grand totals at the bottom
    table.add_section()
    table.add_row(
        "Client Total",
        str(total_count),
        _format_bytes(total_size),
        style="bold yellow"
    )

    console = Console()
    print()
    console.print(table)
    print()


def main():
    """Main function"""

    script_cwd = os.path.abspath(os.path.dirname(__file__))
    logger.add(os.path.join(script_cwd, "logs/seedbox_tools.log"),
        format="{time} - {level} - {message}",
        level=20,
        rotation="1 week",
        compression="gz"
    )

    args = cli()
    config = load_config(script_cwd, args)
    client_name = config.client
    torrent_files = [args.add] if os.path.isfile(args.add) else find_files(args.add, ".torrent", False)

    try:

        # instantiate the selected client
        client = CLIENT_MAP[args.client]()
        client.connect(config)

        if args.add:
            client.upload_torrents(config, torrent_files)
            sys.exit()

        if args.reset_password and client_name == "deluge":
            client.reset_web_password(config)
            sys.exit()

        # get list of all torrents in the client
        all_torrents = client.get_torrents(config)

        if args.list:
            list_torrents(all_torrents)

        if args.summary:
            if isinstance(args.summary_sort, (list, tuple)) and len(args.summary_sort) == 2:
                sort_by = args.summary_sort[0]
                order = args.summary_sort[1].lower()
                descending = True if order in ("desc", "descending", "d") else False
            else:
                sort_by = args.summary_sort[0] if isinstance(args.summary_sort, (list, tuple)) else args.summary_sort
                descending = False
            print_summary(all_torrents, sort_by, descending)

        if args.unregistered:
            client.unregistered_torrents(config, all_torrents)

        if args.move:
            client.move_torrents(config, all_torrents)

        if args.remove:
            client.autoremove_torrents(config, all_torrents)

        if args.export:
            client.export_torrents(config, all_torrents)

    except Exception as err:
        logger.error(err)
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
