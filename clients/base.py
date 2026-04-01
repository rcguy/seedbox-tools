#
# base.py - Base abstract class for torrent clients
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
# Requires - None
#

from abc import ABC, abstractmethod
from models.config import SeedboxConfig
from models.torrent_info import TorrentInfo
from typing import List

class TorrentClient(ABC):

    @abstractmethod
    def connect(self, config: SeedboxConfig):
        pass

    @abstractmethod
    def get_torrents(self, config: SeedboxConfig) -> List[TorrentInfo]:
        pass

    @abstractmethod
    def move_torrents(self, config: SeedboxConfig, torrent_list: List[TorrentInfo]) -> None:
        pass

    @abstractmethod
    def export_torrents(self, config: SeedboxConfig, torrent_list: List[TorrentInfo]) -> None:
        pass

    @abstractmethod
    def autoremove_torrents(self, config: SeedboxConfig, torrent_list: List[TorrentInfo]) -> None:
        pass

    @abstractmethod
    def unregistered_torrents(self, config: SeedboxConfig, torrent_list: List[TorrentInfo]) -> None:
        pass

    @abstractmethod
    def upload_torrents(self, config: SeedboxConfig, torrent_files: List[str]) -> None:
        pass