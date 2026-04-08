"""Obsidian vault writer with atomic file operations."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import yaml
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from onlime.config import get_settings
from onlime.models import ProcessedEvent

logger = structlog.get_logger()

_env: Environment | None = None


def _get_template_env() -> Environment:
    global _env
    if _env is None:
        templates_dir = Path(__file__).parent.parent.parent.parent / "templates"
        _env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _env


# Obsidian/Android sync forbidden: ? " : * | < > \ and control chars
_FORBIDDEN_RE = re.compile(r'[?":*|<>\\]')


def _sanitize_filename(title: str, max_length: int = 80) -> str:
    """Sanitize title for use as Obsidian filename.

    Preserves Unicode, hyphens, and spaces. Removes forbidden chars,
    collapses whitespace, strips trailing dots/spaces from stem.
    """
    clean = _FORBIDDEN_RE.sub(" ", title)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_length:
        clean = clean[:max_length].rsplit(" ", 1)[0]
    return clean.rstrip(". ")


def atomic_write(path: Path, content: str) -> None:
    """Write file atomically via tempfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def build_frontmatter(event: ProcessedEvent, extra: dict | None = None) -> dict:
    """Build YAML frontmatter dict for an Obsidian note."""
    fm: dict = {
        "id": event.raw_event_id,
        "title": event.title,
        "created": event.timestamp.isoformat(),
        "tags": event.tags,
    }
    if event.people:
        fm["people"] = [f"[[{p}]]" for p in event.people]
    if event.category:
        fm["category"] = event.category
    if extra:
        fm.update(extra)
    return fm


def write_note(
    vault_root: Path,
    category_dir: str,
    event: ProcessedEvent,
    template_name: str | None = None,
    extra_frontmatter: dict | None = None,
) -> Path:
    """Write a processed event as a markdown note to the vault.

    Returns the absolute path of the created file.
    """
    # Build filename: sanitize Obsidian-forbidden chars, preserve hyphens and unicode
    title_clean = _sanitize_filename(event.title)
    filename = f"{title_clean}.md"

    note_path = vault_root.expanduser() / category_dir / filename

    # Separate body-only fields (too long for YAML frontmatter)
    _BODY_ONLY_KEYS = {"transcript", "description"}
    body_fields: dict = {}
    fm_extra = dict(extra_frontmatter) if extra_frontmatter else {}
    for key in _BODY_ONLY_KEYS:
        if key in fm_extra:
            body_fields[key] = fm_extra.pop(key)

    # Build content
    fm = build_frontmatter(event, fm_extra)
    fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if template_name:
        env = _get_template_env()
        try:
            template = env.get_template(template_name)
            # Pass body_fields to template alongside frontmatter
            render_fm = {**fm, **body_fields}
            body = template.render(event=event, frontmatter=render_fm)
        except Exception:
            logger.warning("template.failed", template=template_name)
            body = _default_body(event)
    else:
        body = _default_body(event)

    content = f"---\n{fm_str}---\n\n{body}"
    atomic_write(note_path, content)

    logger.info("vault.written", path=str(note_path))
    return note_path


def render_daily_note(date_str: str) -> str:
    """Render a new daily note from template with prev/next date navigation."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    prev_date = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

    env = _get_template_env()
    try:
        template = env.get_template("daily_note.md.j2")
        return template.render(frontmatter={
            "date": date_str,
            "prev_date": prev_date,
            "next_date": next_date,
        })
    except Exception:
        logger.warning("daily_note.template_failed")
        return (
            f"---\ncreated: {date_str}\ntype: daily\n---\n"
            f"## ==잡서\n\n---\n## 일정\n\n---\n## 회고\n\n"
        )


def append_to_daily_note(
    vault_root: Path,
    date: datetime,
    entry_line: str,
    note_link: str,
) -> Path:
    """Append an entry to the daily note's '## ==잡서' section.

    Creates the daily note from template if it doesn't exist.
    Skips if the same note_link is already present (dedup).
    Returns the daily note path.
    """
    settings = get_settings()
    daily_dir = vault_root.expanduser() / settings.vault.daily_dir
    date_str = date.strftime("%Y-%m-%d")
    daily_path = daily_dir / f"{date_str}.md"

    if daily_path.exists():
        content = daily_path.read_text(encoding="utf-8")
    else:
        content = render_daily_note(date_str)

    # Dedup: skip if this note link already exists
    if note_link in content:
        logger.info("daily_note.already_linked", link=note_link)
        return daily_path

    # Find '## ==잡서' section and insert entry (also handle legacy '## 오늘의 기록')
    section_header = "## ==잡서"
    # Normalize legacy section name
    content = content.replace("## 오늘의 기록", section_header, 1)
    if section_header not in content:
        # Append section if missing
        content = content.rstrip() + f"\n\n{section_header}\n\n{entry_line}\n"
    else:
        lines = content.split("\n")
        new_lines: list[str] = []
        inserted = False
        i = 0
        while i < len(lines):
            new_lines.append(lines[i])
            if lines[i].strip() == section_header and not inserted:
                i += 1
                # Collect existing entries until --- or ## heading or end
                while i < len(lines) and not lines[i].startswith("## ") and lines[i].strip() != "---":
                    new_lines.append(lines[i])
                    i += 1
                # Insert new entry before separator
                new_lines.append(entry_line)
                inserted = True
                continue
            i += 1

        content = "\n".join(new_lines)

    atomic_write(daily_path, content)
    logger.info("daily_note.appended", path=str(daily_path), entry=entry_line[:60])
    return daily_path


def _default_body(event: ProcessedEvent) -> str:
    """Simple markdown body when no template is available."""
    parts = []
    if event.summary:
        parts.append(f"## Summary\n\n{event.summary}")
    if event.full_text:
        parts.append(f"## Content\n\n{event.full_text}")
    return "\n\n".join(parts) if parts else event.full_text or ""
