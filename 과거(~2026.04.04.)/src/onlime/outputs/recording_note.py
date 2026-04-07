"""Recording note formatter — phone recordings to Obsidian notes.

Follows the standalone_note.py pattern for consistency.
"""
from __future__ import annotations

import logging
from pathlib import Path

from onlime.config import get_settings
from onlime.connectors.base import ConnectorResult
from onlime.outputs.base import BaseOutputFormatter
from onlime.outputs.templates import render_template
from onlime.vault.io import write_note

logger = logging.getLogger(__name__)


class RecordingNoteFormatter(BaseOutputFormatter):
    """Format phone recordings into Obsidian notes."""

    def format(self, result: ConnectorResult, **kwargs) -> tuple[dict, str]:
        duration_min = int(result.duration_minutes) if result.duration_minutes else None
        file_path = result.metadata.get("file_path", "")
        file_size = result.metadata.get("file_size", 0)
        extension = result.metadata.get("extension", "")

        # Human-readable file size
        if file_size >= 1_048_576:
            size_str = f"{file_size / 1_048_576:.1f} MB"
        elif file_size >= 1024:
            size_str = f"{file_size / 1024:.0f} KB"
        else:
            size_str = f"{file_size} B"

        frontmatter = {
            "created": result.timestamp.strftime("%Y-%m-%d %H:%M"),
            "type": "recording",
            "source": "phone",
        }
        if duration_min is not None:
            frontmatter["duration"] = f"{duration_min}min"
        frontmatter["file_path"] = file_path

        body = render_template(
            "recording.md.j2",
            title=result.title,
            rec_time=result.timestamp.strftime("%Y-%m-%d %H:%M"),
            duration_minutes=duration_min,
            file_path=file_path,
            file_size=size_str,
            extension=extension,
        )

        return frontmatter, body

    def get_output_path(self, result: ConnectorResult, **kwargs) -> Path:
        settings = get_settings()
        date_str = result.timestamp.strftime("%Y%m%d")
        safe_title = result.title.replace("/", "_").replace("\\", "_")
        return settings.vault.inbox_path / f"{date_str}_{safe_title}_Recording.md"


def create_recording_note(result: ConnectorResult, dry_run: bool = False) -> Path:
    """Create an Obsidian note for a phone recording."""
    formatter = RecordingNoteFormatter()
    frontmatter, body = formatter.format(result)
    note_path = formatter.get_output_path(result)

    if not dry_run:
        write_note(note_path, frontmatter, body)

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}녹음 노트 생성: {note_path.name}")
    return note_path
