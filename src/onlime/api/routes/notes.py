"""Recent notes endpoint."""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Query

from onlime.api.models import NoteResponse
from onlime.config.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _classify_note(path: Path, settings) -> str:
    """Classify note type based on its path."""
    path_str = str(path)
    if settings.vault.meeting_dir in path_str:
        return "meeting"
    if settings.vault.daily_dir in path_str:
        return "daily"
    if settings.vault.inbox_dir in path_str:
        return "inbox"
    return "standalone"


def _note_title(path: Path) -> str:
    """Extract title from filename."""
    return path.stem.replace("_", " ")


@router.get("/notes/recent", response_model=list[NoteResponse])
def get_recent_notes(limit: int = Query(20, ge=1, le=100)):
    """Return recently modified notes from the vault."""
    settings = get_settings()
    vault_root = settings.vault.root

    if not vault_root.exists():
        return []

    # Scan key directories for markdown files
    scan_dirs = [
        vault_root / settings.vault.meeting_dir,
        vault_root / settings.vault.daily_dir,
        vault_root / settings.vault.inbox_dir,
    ]

    notes: list[tuple[Path, float]] = []
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for md_file in scan_dir.rglob("*.md"):
            try:
                mtime = md_file.stat().st_mtime
                notes.append((md_file, mtime))
            except OSError:
                continue

    # Sort by modification time, newest first
    notes.sort(key=lambda x: x[1], reverse=True)
    notes = notes[:limit]

    return [
        NoteResponse(
            path=str(path.relative_to(vault_root)),
            title=_note_title(path),
            modified=datetime.fromtimestamp(mtime).isoformat(),
            type=_classify_note(path, settings),
        )
        for path, mtime in notes
    ]
