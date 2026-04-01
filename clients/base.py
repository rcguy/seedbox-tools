# clients/base.py
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