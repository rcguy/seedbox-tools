from dataclasses import dataclass
from typing import Optional


@dataclass
class TorrentInfo:
    name: str
    category: Optional[str] = None
    tags: Optional[str] = None
    infohash: Optional[str] = None
    save_path: Optional[str] = None
    timestamp_finished: Optional[int] = None
    message: Optional[str] = None
    state: Optional[str] = None
    tracker_status: Optional[str] = None
    session_file: Optional[str] = None
    seeding_time: Optional[int] = None
