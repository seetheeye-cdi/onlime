"""Recording sync connector — watch synced folder for new phone recordings.

Scans ~/Recordings/synced (Syncthing target) for new audio files,
extracts metadata, and returns ConnectorResults for processing.
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector, ConnectorResult
from onlime.connectors.registry import register

logger = logging.getLogger(__name__)


def _get_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().general.timezone)


def _get_duration_seconds(file_path: Path) -> float | None:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def _file_created_time(file_path: Path) -> datetime:
    """Get file creation time (birthtime on macOS, mtime fallback)."""
    tz = _get_tz()
    stat = file_path.stat()
    # macOS supports st_birthtime
    ts = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return datetime.fromtimestamp(ts, tz=tz)


def _file_to_connector_result(file_path: Path) -> ConnectorResult:
    """Convert an audio file to a ConnectorResult."""
    settings = get_settings()
    tz = _get_tz()
    created = _file_created_time(file_path)
    size_bytes = file_path.stat().st_size

    duration_sec = _get_duration_seconds(file_path)
    duration_min = duration_sec / 60 if duration_sec else None

    # Use file stem as title, clean up common prefixes
    title = file_path.stem

    # source_id: relative path from watch_dir for uniqueness
    watch_dir = settings.recording_sync.resolved_watch_dir
    try:
        rel = file_path.relative_to(watch_dir)
        source_id = str(rel)
    except ValueError:
        source_id = file_path.name

    return ConnectorResult(
        source_id=source_id,
        source_type="recording",
        connector_name="recording_sync",
        timestamp=created,
        title=title,
        content="",
        participants=[],
        duration_minutes=duration_min,
        metadata={
            "file_path": str(file_path),
            "file_size": size_bytes,
            "extension": file_path.suffix.lower(),
            "source_device": "phone",
        },
        raw={
            "file_path": str(file_path),
            "file_name": file_path.name,
            "size_bytes": size_bytes,
            "duration_seconds": duration_sec,
        },
    )


@register
class RecordingSyncConnector(BaseConnector):
    """Watch synced folder for new phone recordings."""

    name = "recording_sync"

    def fetch(self, **kwargs) -> list[ConnectorResult]:
        """Scan watch_dir for audio files and return new ones."""
        settings = get_settings()
        watch_dir = settings.recording_sync.resolved_watch_dir

        if not watch_dir.is_dir():
            logger.warning(f"녹음 동기화 폴더가 없습니다: {watch_dir}")
            return []

        extensions = set(settings.recording_sync.extensions)
        results = []

        for root, _dirs, files in os.walk(watch_dir):
            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in extensions:
                    try:
                        result = _file_to_connector_result(fpath)
                        results.append(result)
                    except Exception as e:
                        logger.error(f"파일 처리 실패 {fpath}: {e}")

        # Sort by timestamp (newest first)
        results.sort(key=lambda r: r.timestamp, reverse=True)
        logger.info(f"동기화 폴더에서 녹음 {len(results)}개 발견")
        return results

    def is_available(self) -> bool:
        settings = get_settings()
        return settings.recording_sync.enabled
