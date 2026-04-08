"""Background task: sync today's Google Calendar events to daily note."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import structlog

from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask
from onlime.outputs.vault import atomic_write

logger = structlog.get_logger()


def _replace_schedule_section(content: str, schedule_text: str) -> str:
    """Replace the '## 일정' section content in a daily note.

    Preserves everything before and after the section (including ---
    separators). Replaces the section body with schedule_text.
    """
    lines = content.split("\n")
    new_lines: list[str] = []
    i = 0
    replaced = False

    while i < len(lines):
        if lines[i].strip() in ("## 일정", "## 오늘의 일정") and not replaced:
            lines[i] = "## 일정"  # normalize old name
            new_lines.append(lines[i])
            new_lines.append("")
            new_lines.append(schedule_text)
            new_lines.append("")
            # Skip old section body until --- or ## or end
            i += 1
            while i < len(lines) and not lines[i].startswith("## ") and lines[i].strip() != "---":
                i += 1
            replaced = True
            continue
        new_lines.append(lines[i])
        i += 1

    if not replaced:
        # Section not found — append it
        new_lines.append("")
        new_lines.append("## 일정")
        new_lines.append("")
        new_lines.append(schedule_text)
        new_lines.append("")

    return "\n".join(new_lines)


class GCalSyncTask(BackgroundTask):
    """Sync today's GCal events to daily note every N minutes."""

    name = "gcal_sync"

    async def run_once(self) -> None:
        from pathlib import Path

        from onlime.connectors.gcal import format_events_text, get_events

        # Skip if GCal not set up yet
        settings = get_settings()
        token_path = Path(settings.gcal.token_file).expanduser()
        if not token_path.exists():
            logger.info("gcal_sync.skipped", reason="token.json not found")
            return

        settings = get_settings()
        vault_root = settings.vault.root.expanduser()
        daily_dir = vault_root / settings.vault.daily_dir

        # Fetch today's events
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_forward = getattr(settings.gcal, "sync_days_forward", 1)
        today_end = today_start + timedelta(days=days_forward)

        events = await get_events(today_start, today_end)
        schedule_text = format_events_text(events)

        # Update daily note
        date_str = now.strftime("%Y-%m-%d")
        daily_path = daily_dir / f"{date_str}.md"

        if daily_path.exists():
            content = daily_path.read_text(encoding="utf-8")
        else:
            from onlime.outputs.vault import render_daily_note
            content = render_daily_note(date_str)

        updated = _replace_schedule_section(content, schedule_text)
        atomic_write(daily_path, updated)

        logger.info(
            "gcal_sync.cycle",
            events=len(events),
            daily_note=date_str,
        )
