"""
Temporary file management for stateless upload → calculate workflow.

Flow:
  1. /api/upload/<type> saves file with uuid4 as file_id under temp_uploads/
  2. Returns file_id to client
  3. Client POST /api/calculate with the file_ids
  4. Server reads files by id, runs calculation, returns full results
  5. Client keeps results in memory/localStorage (stateless on server)

TTL:
  Files older than TTL are purged on next upload (lazy cleanup).
  Default 60 min: enough for a calculation round-trip, short enough
  to limit disk usage on free-tier deployment.

Security:
  - file_id is uuid4 (unguessable)
  - Filename from client is only used for display, not for saving
  - Saved filename is `{file_id}{ext}` to prevent path traversal

Version: 1.0.0
Last Updated: 2026-04-15
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level directory; configurable via init_temp_dir()
_TEMP_DIR: Path = Path("temp_uploads")

# Extensions we accept. Saved files keep the original extension so that
# pandas / openpyxl can dispatch correctly by suffix.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls"})


def init_temp_dir(path: str | Path = "temp_uploads") -> Path:
    """
    Initialize the temp directory (idempotent).

    Call once at app startup. Returns the resolved Path.
    """
    global _TEMP_DIR
    _TEMP_DIR = Path(path)
    _TEMP_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Temp dir initialized: {_TEMP_DIR.resolve()}")
    return _TEMP_DIR


def get_temp_dir() -> Path:
    """Return the current temp directory."""
    return _TEMP_DIR


def get_temp_path(file_id: str, ext: str) -> Path:
    """
    Build the full path for a given file_id + extension.

    Caller is responsible for validating file_id / ext.
    """
    if not ext.startswith("."):
        ext = f".{ext}"
    return _TEMP_DIR / f"{file_id}{ext}"


def find_file(file_id: str) -> Optional[Path]:
    """
    Locate a file by its file_id regardless of extension.

    Returns None if not found or file_id is invalid.
    Uses glob so we don't require caller to remember the extension.
    """
    if not file_id or not isinstance(file_id, str):
        return None

    # Defensive: prevent any path-traversal by rejecting separators
    if "/" in file_id or "\\" in file_id or ".." in file_id:
        logger.warning(f"Rejected suspicious file_id: {file_id!r}")
        return None

    matches = list(_TEMP_DIR.glob(f"{file_id}.*"))
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(f"Multiple files found for id {file_id}: {[m.name for m in matches]}")
    return matches[0]


def delete_file(file_id: str) -> bool:
    """
    Delete a temp file by id. Returns True if deleted, False if not found.
    """
    path = find_file(file_id)
    if path is None:
        return False
    try:
        path.unlink(missing_ok=True)
        logger.info(f"Deleted temp file: {path.name}")
        return True
    except OSError as e:
        logger.error(f"Failed to delete {path.name}: {e}")
        return False


def cleanup_temp_files(ttl_minutes: int = 60) -> int:
    """
    Remove files whose mtime is older than ttl_minutes.

    Intended to be called on every upload (lazy cleanup). No background
    thread needed — the usage pattern is low-frequency.

    Returns the number of files deleted.
    """
    if not _TEMP_DIR.exists():
        return 0

    cutoff = time.time() - (ttl_minutes * 60)
    removed = 0

    for entry in _TEMP_DIR.iterdir():
        try:
            if not entry.is_file():
                continue
            if entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
                removed += 1
                logger.info(f"Cleaned expired temp file: {entry.name}")
        except OSError as e:
            # One bad file shouldn't stop the whole sweep
            logger.warning(f"Failed to clean {entry.name}: {e}")

    if removed:
        logger.info(f"Cleanup removed {removed} expired file(s)")
    return removed


def is_allowed_extension(ext: str) -> bool:
    """Whitelist check for uploaded file extensions."""
    if not ext:
        return False
    ext = ext.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext in ALLOWED_EXTENSIONS


__all__ = [
    "init_temp_dir",
    "get_temp_dir",
    "get_temp_path",
    "find_file",
    "delete_file",
    "cleanup_temp_files",
    "is_allowed_extension",
    "ALLOWED_EXTENSIONS",
]
