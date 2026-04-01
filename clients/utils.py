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
# Updated - 2026-04-01
# Version - 1.1.0
# Requires - loguru
#

"""
Shared utilities for torrent client implementations.

This module provides common functions for file operations, directory management,
and torrent session handling used across different torrent clients (Deluge, rTorrent, qBittorrent).
Includes utilities for exporting torrents, creating zip archives, and managing directories.
"""

from __future__ import annotations
import os
import sys
import shutil
import fnmatch
import tempfile
import zipfile
from pathlib import Path
from loguru import logger
from datetime import datetime
from typing import Iterable, Optional, List, Union
from models.config import SeedboxConfig
from models.torrent_info import TorrentInfo

def export_session_torrents(config: SeedboxConfig, torrent_list: List[TorrentInfo], zip_prefix: str = "export") -> None:
    """Copy torrent session files into `config.export_dir/<timestamp>/<category>` and optionally zip them.

    Creates a timestamped directory structure, copies .torrent files by category,
    and optionally creates a zip archive of the exported files.

    Args:
        config: SeedboxConfig with export_dir, zip_export, and dry_run settings.
        torrent_list: List of TorrentInfo objects (must include `session_file`).
        zip_prefix: Prefix for the zip filename (e.g., 'Deluge' or 'rTorrent').

    Returns:
        None

    Side effects:
        Creates directories, copies files, and may create/delete zip archives.
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

def find_files(input_path: Union[str, Path], file_exts: list[str], recursive: bool) -> list[str]:
    """Scan directory and locate files with matching extensions.

    Recursively scans the directory if requested, collecting absolute paths
    of files whose extensions match the provided list.

    Args:
        input_path: Directory path to scan (string or Path).
        file_exts: List of file extensions to match (e.g., ['.torrent', '.mp4']).
        recursive: Whether to scan subdirectories recursively.

    Returns:
        List of absolute path strings for matching files.

    Raises:
        FileNotFoundError: If input_path does not exist.
        NotADirectoryError: If input_path is not a directory.
        PermissionError: If permission denied accessing the directory.
        OSError: For other I/O errors during scanning.
    """
    directory = Path(input_path)

    if not directory.exists():
        logger.error(f"Directory not found: '{directory}'")
        raise FileNotFoundError(directory)

    if not directory.is_dir():
        logger.error(f"Path is not a directory: '{directory}'")
        raise NotADirectoryError(directory)

    file_list: list[str] = []

    try:
        for entry in directory.iterdir():
            try:
                if entry.is_file():
                    ext = entry.suffix.lower()
                    if ext in file_exts:
                        file_list.append(str(entry.resolve()))
                elif recursive and entry.is_dir():
                    file_list.extend(find_files(entry, file_exts, True))
            except OSError as err:
                logger.error(f"Error scanning entry '{entry}': {err}")
                continue
    except PermissionError as err:
        logger.error(f"Permission denied: '{directory}'")
        raise
    except OSError as err:
        logger.error(f"Error scanning directory '{directory}': {err}")
        raise

    return file_list

def _matches_any(path: str, patterns: Optional[Iterable[str]]) -> bool:
    """Check if a path matches any of the given glob patterns.

    Args:
        path: The path string to check.
        patterns: Iterable of glob patterns to match against.

    Returns:
        True if path matches any pattern, False otherwise.
    """
    if not patterns:
        return False
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
    return False

def create_zip(
    src_dir: str,
    dest_zip: Optional[str] = None,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    compression: int = zipfile.ZIP_DEFLATED,
    compresslevel: Optional[int] = 9,
    follow_symlinks: bool = False,
) -> str:
    """Create a zip archive containing files under src_dir.

    Recursively walks the source directory, applying include/exclude filters,
    and creates a compressed zip archive. Uses temporary files for atomic writes.

    Args:
        src_dir: Source directory to archive (walked recursively).
        dest_zip: Optional destination zip path. If None, creates timestamped file.
        include: List of glob patterns to include (applied to relative paths).
        exclude: List of glob patterns to exclude (applied to relative paths).
        compression: Zipfile compression method (e.g., ZIP_DEFLATED).
        compresslevel: Compression level (Python 3.7+), None for default.
        follow_symlinks: Whether to follow symlinks during directory walk.

    Returns:
        Path to the created zip file.

    Raises:
        ValueError: If src_dir is invalid or no files found.
        OSError: For I/O errors during zip creation.
        zipfile.BadZipFile: For zip file corruption issues.
    """
    src_dir = os.path.abspath(src_dir)

    if not os.path.isdir(src_dir):
        logger.error(f"Source directory does not exist or is not a directory: {src_dir}")
        raise ValueError(f"Invalid source directory: {src_dir}")

    parent_dir = os.path.dirname(src_dir.rstrip(os.sep))
    if not parent_dir:
        parent_dir = os.getcwd()

    if dest_zip:
        dest_zip = os.path.abspath(dest_zip)
        dest_parent = os.path.dirname(dest_zip)
        if dest_parent and not os.path.exists(dest_parent):
            try:
                os.makedirs(dest_parent, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create destination parent dir {dest_parent}: {e}")
                raise
    else:
        timestamp = datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        dest_zip = os.path.join(parent_dir, f"{parent_dir}_{timestamp}.zip")

    logger.debug(f"Creating zip archive of {src_dir} -> {dest_zip}")

    tmp_dir = os.path.dirname(dest_zip) or parent_dir
    tmp_fd = None
    tmp_path = None
    zf: Optional[zipfile.ZipFile] = None

    try:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp_exported_torrents_", suffix=".zip", dir=tmp_dir)
        os.close(tmp_fd)
        tmp_fd = None

        zf_kwargs = {}
        if compresslevel is not None:
            zf_kwargs["compresslevel"] = compresslevel

        try:
            zf = zipfile.ZipFile(tmp_path, mode="w", compression=compression, **zf_kwargs)
        except TypeError:
            logger.debug("ZipFile does not accept 'compresslevel' (falling back without it).")
            zf = zipfile.ZipFile(tmp_path, mode="w", compression=compression)

        files_added = 0
        for root, dirs, files in os.walk(src_dir, followlinks=follow_symlinks):
            rel_root = os.path.relpath(root, src_dir)
            if rel_root == ".":
                rel_root = ""

            for fname in files:
                full_path = os.path.join(root, fname)
                rel_path = os.path.join(rel_root, fname) if rel_root else fname

                if exclude and _matches_any(rel_path, exclude):
                    logger.debug(f"Skipping excluded file: {rel_path}")
                    continue

                if include:
                    if not _matches_any(rel_path, include):
                        logger.debug(f"Skipping non-matching include pattern: {rel_path}")
                        continue

                try:
                    zf.write(full_path, arcname=rel_path)
                    files_added += 1
                except Exception as e:
                    logger.error(f"Failed to add file to zip: {full_path} ({e})")
                    raise

        if zf is not None:
            zf.close()
            zf = None

        if files_added == 0:
            logger.warning("No files added to the zip archive. Removing temporary file.")
            try:
                os.remove(tmp_path)
            except Exception:
                logger.debug(f"Failed to remove empty temporary zip {tmp_path}")
            raise ValueError("No files were found to archive in " + src_dir)

        try:
            shutil.move(tmp_path, dest_zip)
            tmp_path = None
        except Exception as e:
            logger.error(f"Failed to move temporary zip to destination: {e}")
            raise

        final_size = os.path.getsize(dest_zip)
        logger.success(f"Zip archive created: {dest_zip} ({final_size/1024/1024:.2f} MB, {files_added} files)")
        return dest_zip

    except Exception:
        logger.error(f"Failed to create zip archive for {src_dir}")
        raise
    finally:
        if zf is not None:
            try:
                zf.close()
            except Exception:
                logger.debug("Error closing zipfile during cleanup")
        if tmp_fd:
            try:
                os.close(tmp_fd)
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                logger.debug(f"Removed temporary file {tmp_path}")
            except Exception:
                logger.debug(f"Failed to remove temporary file {tmp_path} during cleanup")

def make_dir(input_dir: Union[str, Path]) -> bool:
    """Create a directory and all necessary parent directories.

    Safely creates directories without failing if they already exist.

    Args:
        input_dir: Directory path to create (string or Path).

    Returns:
        True if directory was created, False if it already existed.

    Raises:
        PermissionError: If permission denied creating the directory.
        OSError: For other I/O errors during directory creation.
    """
    path = Path(input_dir)

    if path.exists():
        return False

    try:
        path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created directory: '{path}'")
        return True
    except PermissionError as exc:
        logger.error(f"Permission denied creating directory: '{path}'")
        raise
    except OSError as exc:
        logger.error(f"Failed to create directory '{path}': {exc}")
        raise

def delete_files(data_path: Union[str, Path]) -> bool:
    """Delete a file, symlink, or directory from disk.

    Handles files, symlinks, and directories recursively. Returns False
    if the path does not exist, without raising an error.

    Args:
        data_path: Path to the file or directory to delete (string or Path).

    Returns:
        True if deletion succeeded, False if path did not exist.

    Raises:
        PermissionError: If permission denied deleting the path.
        OSError: For other I/O errors during deletion.
    """
    path = Path(data_path)

    if not path.exists():
        logger.warning(f"No such file or directory: '{path}'")
        return False

    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
            logger.info(f"File deleted: {path}")
        elif path.is_dir():
            shutil.rmtree(path)
            logger.info(f"Directory deleted: {path}")
        else:
            path.unlink()
            logger.info(f"Deleted special path: {path}")

        return True
    except PermissionError as exc:
        logger.error(f"Permission denied deleting: '{path}'")
        raise
    except OSError as exc:
        logger.error(f"Failed to delete '{path}': {exc}")
        raise