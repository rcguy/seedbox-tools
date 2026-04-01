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

from __future__ import annotations
import os
import sys
import shutil
import fnmatch
import tempfile
import zipfile
from loguru import logger
from datetime import datetime
from typing import Iterable, Optional, List
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

def find_files(input_path: str, file_exts: list, recursive: bool) -> list:
    """Scan directory and locate files"""

    file_list = list()

    try:
        with os.scandir(os.path.realpath(input_path, strict=True)) as scan:
            for entry in scan:
                try:
                    if entry.is_file():
                        file_ext = os.path.splitext(entry)[1].lower()
                        if file_ext in file_exts:
                            file_list.append(entry.path)
                            continue
                    elif recursive and entry.is_dir(follow_symlinks=False):
                        files = find_files(entry.path, file_exts, True)
                        file_list = [*file_list, *files]
                except OSError as err:
                    logger.error(f"'{err}'")
                    continue
    except FileNotFoundError:
        logger.error(f"Directory not found: '{os.path.basename(input_path)}'")
        sys.exit(1)
    except PermissionError:
        logger.error(f"Permission denied: '{os.path.basename(input_path)}'")
        sys.exit(1)
    except Exception as err:
        logger.error(err)
        sys.exit(1)

    return file_list

def _matches_any(path: str, patterns: Optional[Iterable[str]]) -> bool:
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
    """
    Create a zip archive containing the files under `src_dir`.

    Parameters:
    - src_dir: directory whose contents will be archived (walked recursively).
    - dest_zip: optional destination zip file path. If None, a timestamped
      file will be created inside the parent of `src_dir`.
    - include: list of glob patterns to explicitly include (applied to relative path).
               If None or empty, all files are considered for inclusion.
    - exclude: list of glob patterns to exclude (applied to relative path).
    - compression: `zipfile` compression method (e.g., ZIP_STORED, ZIP_DEFLATED).
    - compresslevel: optional compression level (Python 3.7+).
    - follow_symlinks: whether to follow symlinks when walking.

    Returns:
    - The final path to the created zip file.

    Raises:
    - OSError, zipfile.BadZipFile, ValueError for invalid inputs or I/O failures.
      Exceptions are logged before being raised.
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

def make_dir(input_dir: str) -> bool:
    """Make new directory if necessary"""

    try:
        if not os.path.exists(os.path.realpath(input_dir)):
            os.makedirs(input_dir, exist_ok=True)
            logger.info(f"Created directory: '{input_dir}'")
            return True
    except PermissionError:
        logger.error(f"Permission denied creating directory: '{input_dir}'")
        sys.exit(1)
    except Exception as err:
        logger.error(err)
        sys.exit(1)

    return False

def delete_files(data_path: str) -> bool:
    """Delete files from disk"""

    data_path = os.path.realpath(data_path)

    try:
        
        if os.path.isfile(data_path):
            os.remove(data_path)
            logger.info(f"File Deleted: {os.path.basename(data_path)}")
        elif os.path.isdir(data_path):
            shutil.rmtree(data_path)
            logger.info(f"Directory Deleted: {data_path}")

        return True

    except FileNotFoundError:
        logger.error(f"No such file or directory:: '{data_path}'")
    except PermissionError:
        logger.error(f"Permission Denied: '{data_path}'")
    except Exception as err:
        logger.error(f"'{err}'")

    return False