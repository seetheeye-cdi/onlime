"""Obsidian vault writer with atomic file operations."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
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


def append_to_daily_note(
    vault_root: Path,
    date: datetime,
    entry_line: str,
    note_link: str,
) -> Path:
    """Append an entry to the daily note's '## 오늘의 기록' section.

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
        # Create from template
        env = _get_template_env()
        try:
            template = env.get_template("daily_note.md.j2")
            content = template.render(frontmatter={"date": date_str})
        except Exception:
            logger.warning("daily_note.template_failed")
            content = f"# {date_str}\n\n## 오늘의 일정\n\n## 오늘의 기록\n\n## Daily Summary\n"

    # Dedup: skip if this note link already exists
    if note_link in content:
        logger.info("daily_note.already_linked", link=note_link)
        return daily_path

    # Find '## 오늘의 기록' section and insert entry
    section_header = "## 오늘의 기록"
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
                # Skip placeholder line if present
                if i + 1 < len(lines) and "수집된 데이터가" in lines[i + 1]:
                    i += 1  # skip placeholder
                # Find the end of existing entries (before next ## or end)
                i += 1
                while i < len(lines) and lines[i].strip() and not lines[i].startswith("## "):
                    new_lines.append(lines[i])
                    i += 1
                # Insert blank line before entry if needed
                if new_lines[-1].strip() != "" and new_lines[-1].strip() != section_header:
                    pass  # entries are contiguous
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
