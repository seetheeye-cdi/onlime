"""GDrive/local folder watcher using watchdog for voice recordings."""

from __future__ import annotations

import asyncio
import fnmatch
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector
from onlime.connectors.registry import register
from onlime.models import ContentType, SourceType

logger = structlog.get_logger()

_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".wma"}


class _FileHandler(FileSystemEventHandler):
    """Watchdog handler that pushes new audio files to the engine queue."""

    def __init__(self, queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop) -> None:
        self._queue = queue
        self._loop = loop
        settings = get_settings()
        self._ignore = settings.gdrive.ignore_patterns
        self._stability_delay = settings.gdrive.stability_delay_seconds

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Check ignore patterns
        for pattern in self._ignore:
            if fnmatch.fnmatch(path.name, pattern):
                return

        # Only process audio files
        if path.suffix.lower() not in _AUDIO_EXTENSIONS:
            return

        # Schedule async processing on the event loop
        asyncio.run_coroutine_threadsafe(self._handle_file(path), self._loop)

    async def _handle_file(self, path: Path) -> None:
        """Wait for file stability then emit event."""
        # Wait for file to finish writing
        await asyncio.sleep(self._stability_delay)

        if not path.exists():
            return

        event_dict = _build_event(path)
        await self._queue.put(event_dict)
        logger.info("gdrive.file_detected", path=str(path))


def _build_event(path: Path) -> dict[str, Any]:
    """Build an event dict from an audio file path with stable ID for dedup."""
    stat = path.stat()
    file_mtime = datetime.fromtimestamp(stat.st_mtime)
    # Stable ID based on filename — Samsung filenames include timestamps so they're unique.
    # This prevents reprocessing on daemon restart.
    stable_id = f"gdrive:{path.name}"
    return {
        "id": stable_id,
        "source": SourceType.GDRIVE.value,
        "content_type": ContentType.VOICE.value,
        "raw_content": f"[음성 파일] {path.name}",
        "timestamp": file_mtime.isoformat(),
        "metadata": {
            "file_path": str(path),
            "file_name": path.name,
            "file_size": stat.st_size,
        },
    }


class GDriveRescanTask:
    """Periodic rescan to catch files missed during macOS sleep.

    Uses the same BackgroundTask interface but imported lazily to avoid
    circular imports (maintenance.base imports state.store).
    """

    name = "gdrive_rescan"

    def __init__(self, interval_seconds: int = 1800,
                 queue: asyncio.Queue[dict[str, Any]] | None = None) -> None:
        from onlime.maintenance.base import BackgroundTask

        # Dynamically create a BackgroundTask subclass bound to this instance
        outer = self
        self._queue = queue

        class _Task(BackgroundTask):
            name = "gdrive_rescan"

            async def run_once(self_inner) -> None:
                await outer._rescan()

        self._bg = _Task(interval_seconds)

    async def _rescan(self) -> None:
        settings = get_settings()
        count = 0
        for watch_path in settings.gdrive.watch_paths:
            resolved = Path(watch_path).expanduser()
            if not resolved.exists():
                continue
            for path in resolved.rglob("*"):
                if path.is_dir():
                    continue
                if path.suffix.lower() not in _AUDIO_EXTENSIONS:
                    continue
                skip = False
                for pattern in settings.gdrive.ignore_patterns:
                    if fnmatch.fnmatch(path.name, pattern):
                        skip = True
                        break
                if skip:
                    continue
                await self._queue.put(_build_event(path))
                count += 1
        if count:
            logger.info("gdrive.rescan", files=count)

    async def start(self, store=None) -> None:
        await self._bg.start(store)

    async def stop(self) -> None:
        await self._bg.stop()

    def status(self) -> dict[str, Any]:
        return self._bg.status()


@register
class GDriveConnector(BaseConnector):
    """Watch local/GDrive folders for new audio files."""

    name = "gdrive"

    def __init__(self) -> None:
        self._observer: Observer | None = None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None

    def fetch(self, **kwargs: Any) -> list:
        """Not used for push-based connector."""
        return []

    async def start(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Start watching configured directories + scan existing files."""
        settings = get_settings()
        if not settings.gdrive.watch_paths:
            logger.warning("gdrive.no_watch_paths")
            return

        self._queue = queue
        loop = asyncio.get_running_loop()
        handler = _FileHandler(queue, loop)
        self._observer = Observer()

        for watch_path in settings.gdrive.watch_paths:
            resolved = Path(watch_path).expanduser()
            if resolved.exists():
                self._observer.schedule(handler, str(resolved), recursive=True)
                logger.info("gdrive.watching", path=str(resolved))
            else:
                logger.warning("gdrive.path_not_found", path=str(resolved))

        self._observer.start()

        # Scan existing files (dedup handled by stable ID in state DB)
        await self._initial_scan(settings)
        logger.info("gdrive.started")

    async def _initial_scan(self, settings: Any) -> None:
        """Scan existing audio files and emit events for unprocessed ones."""
        count = 0
        for watch_path in settings.gdrive.watch_paths:
            resolved = Path(watch_path).expanduser()
            if not resolved.exists():
                continue
            for path in resolved.rglob("*"):
                if path.is_dir():
                    continue
                if path.suffix.lower() not in _AUDIO_EXTENSIONS:
                    continue
                # Skip ignored patterns
                skip = False
                for pattern in settings.gdrive.ignore_patterns:
                    if fnmatch.fnmatch(path.name, pattern):
                        skip = True
                        break
                if skip:
                    continue

                event_dict = _build_event(path)
                await self._queue.put(event_dict)
                count += 1
        if count:
            logger.info("gdrive.initial_scan", files=count)

    async def stop(self) -> None:
        """Stop the file watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("gdrive.stopped")

    def is_available(self) -> bool:
        settings = get_settings()
        return bool(settings.gdrive.watch_paths)
