"""Standalone note formatter for unmatched Plaud recordings.

Ported from past/plaud_sync.py (create_standalone_transcript_note).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.base import ConnectorResult
from onlime.connectors.plaud import (
    parse_recording_time, get_recording_duration, get_recording_id,
)
from onlime.outputs.base import BaseOutputFormatter
from onlime.outputs.templates import render_template
from onlime.vault.io import write_note

logger = logging.getLogger(__name__)


class StandaloneNoteFormatter(BaseOutputFormatter):
    """Format Plaud recordings into standalone Obsidian notes."""

    def format(self, result: ConnectorResult, **kwargs) -> tuple[dict, str]:
        frontmatter = {
            "created": result.timestamp.strftime("%Y-%m-%d %H:%M"),
            "type": "transcription",
            "source": "plaud",
            "plaud_id": result.source_id,
        }

        body = render_template(
            'standalone.md.j2',
            title=result.title,
            rec_time=result.timestamp.strftime('%Y-%m-%d %H:%M'),
            duration_minutes=int(result.duration_minutes or 0),
            summary=kwargs.get('summary_md'),
            outline=kwargs.get('outline_md'),
            transcript=kwargs.get('transcript_md'),
        )

        return frontmatter, body

    def get_output_path(self, result: ConnectorResult, **kwargs) -> Path:
        settings = get_settings()
        date_str = result.timestamp.strftime("%Y%m%d")
        safe_title = result.title.replace("/", "_").replace("\\", "_")
        return settings.vault.inbox_path / f"{date_str}_{safe_title}_Plaud.md"


def create_standalone_transcript_note(
    recording: dict, transcript_md: str, summary_md: str | None,
    outline_md: str | None = None, dry_run: bool = False,
) -> Path:
    """Create a standalone transcription note in the Inbox when no calendar match."""
    settings = get_settings()
    tz = ZoneInfo(settings.general.timezone)

    rec_time = parse_recording_time(recording)
    if not rec_time:
        rec_time = datetime.now(tz=tz)

    rec_id = get_recording_id(recording)
    title = recording.get("filename", f"녹음_{rec_time.strftime('%H%M')}")
    date_str = rec_time.strftime("%Y%m%d")

    frontmatter = {
        "created": rec_time.strftime("%Y-%m-%d %H:%M"),
        "type": "transcription",
        "source": "plaud",
        "plaud_id": rec_id,
    }

    duration = get_recording_duration(recording)
    body = render_template(
        'standalone.md.j2',
        title=title,
        rec_time=rec_time.strftime('%Y-%m-%d %H:%M'),
        duration_minutes=int(duration.total_seconds() // 60),
        summary=summary_md,
        outline=outline_md,
        transcript=transcript_md,
    )

    safe_title = title.replace("/", "_").replace("\\", "_")
    note_path = settings.vault.inbox_path / f"{date_str}_{safe_title}_Plaud.md"

    if not dry_run:
        write_note(note_path, frontmatter, body)

    logger.info(f"Created standalone transcript: {note_path.name}")
    return note_path
