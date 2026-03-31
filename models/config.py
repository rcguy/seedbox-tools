from dataclasses import dataclass, field
from typing import Dict, Optional
from my_utils import load_yaml
import os

@dataclass
class DelugeConfig:
    """Deluge-specific configuration."""
    host: str = "localhost"
    port: int = 58846
    url: str
    password: str
    cfg_dir: str
    
    @property
    def conn_info(self) -> Dict[str, str]:
        """Connection info for Deluge."""
        return {
            "url": self.url,
            "password": self.password,
        }

    @property
    def state_dir(self) -> str:
        return os.path.join(self.cfg_dir, "state")
    
    @property
    def web_cfg_path(self) -> str:
        return os.path.join(self.cfg_dir, "web.conf")

@dataclass
class qBittorrentConfig:
    """qBittorrent-specific configuration."""
    host: str
    port: int
    username: str
    password: str

    @property
    def conn_info(self) -> Dict[str, int, str, str]:
        """Connection info for qBittorrent."""
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
        }

@dataclass
class rTorrentConfig:
    """rTorrent-specific configuration."""
    server_url: str

@dataclass
class SeedboxConfig:
    """Seedbox default configuration."""
    dry_run: bool
    cfg_path: str
    skip_labels: list
    sleep_time: int
    category_seed_time: Dict[str, int] = field(default_factory=dict)
    minimum_seed_time: int
    nvme_time: int
    nvme_dir: str
    rust_dir: str
    export_dir: str = ""
    deluge: DelugeConfig
    qbittorrent: qBittorrentConfig
    rtorrent: rTorrentConfig
    filter_dict: Dict[str, str] = field(default_factory=dict)
    torrent_label: Optional[str] = None
    torrent_tag: Optional[str] = ""
    torrent_save_path: Optional[str] = None
    torrent_status: Optional[str] = None


def load_config(script_cwd: str, cli_opts: argparse.Namespace) -> SeedboxConfig:
    """Load and merge config from file and CLI args."""
    args = cli_opts
    
    # Determine config file path
    cfg_path = os.path.abspath(args.config) if args.config else os.path.join(script_cwd, "cfg/seedbox.yaml")
    cfg = load_yaml(cfg_path)["Seedbox"]
    
    # Parse filter dict from CLI
    filter_dict = dict(map(lambda s: s.split('='), args.filter)) if args.filter else {}
    
    # Determine export dir
    export_dir = os.path.abspath(args.export_dir) if args.export_dir else os.path.join(script_cwd, cfg["export_dir"])
    
    # Create DelugeConfig
    deluge = DelugeConfig(
        host=cfg["Deluge"]["host"],
        port=cfg["Deluge"]["port"],
        url=cfg["Deluge"]["url"],
        password=cfg["Deluge"]["password"],
        cfg_dir=cfg["Deluge"]["cfg_dir"],
    )

    # Create qBittorrentConfig
    qbittorrent = qBittorrentConfig(
        host=cfg["qBittorrent"]["host"],
        port=cfg["qBittorrent"]["port"],
        username=cfg["qBittorrent"]["username"],
        password=cfg["qBittorrent"]["password"],
    )

    # Create rTorrentConfig
    rtorrent = rTorrentConfig(
        server_url=cfg["rTorrent"]["server_url"],
    )
    
    # Create main SeedboxConfig with CLI args overriding file config
    config = SeedboxConfig(
        dry_run=args.dry_run,
        cfg_path=cfg_path,
        skip_labels=args.skip_labels if args.skip_labels else cfg["skip_labels"],
        sleep_time=cfg["sleep_time"],
        category_seed_time=cfg["category_seed_time"],
        minimum_seed_time=args.seed_time if args.seed_time else cfg["minimum_seed_time"],
        nvme_time=args.nvme_time if args.nvme_time else cfg["nvme_cache_time"],
        nvme_dir=cfg["nvme_dir"],
        rust_dir=cfg["rust_dir"],
        export_dir=export_dir,
        deluge=deluge,
        qbittorrent=qbittorrent,
        rtorrent=rtorrent,
        filter_dict=filter_dict,
        torrent_label=args.label,
        torrent_tag=args.tag if args.tag else "",
        torrent_save_path=args.path,
        torrent_status=args.status,
    )
    
    return config
