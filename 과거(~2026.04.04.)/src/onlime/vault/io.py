"""Obsidian markdown file I/O: frontmatter parsing, sync block management.

Ported from past/vault_io.py with type hints and settings integration.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
SYNC_BLOCK_RE = re.compile(
    r'<!-- SYNC:(\S+) -->\n(.*?)<!-- /SYNC:\1 -->',
    re.DOTALL
)


def read_note(path: Path) -> tuple[dict, str]:
    """Parse an Obsidian note into (frontmatter_dict, body_string)."""
    text = path.read_text(encoding='utf-8')
    m = FRONTMATTER_RE.match(text)
    if m:
        fm = yaml.safe_load(m.group(1)) or {}
        body = text[m.end():]
    else:
        fm = {}
        body = text
    return fm, body


def write_note(path: Path, frontmatter: dict, body: str) -> None:
    """Write frontmatter + body back to an Obsidian note (atomic write)."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fm_str = yaml.dump(
        frontmatter, allow_unicode=True,
        default_flow_style=False, sort_keys=False,
    )
    content = f"---\n{fm_str}---\n{body}"
    # Use a unique temp file to avoid race conditions from concurrent writes.
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp"
    )
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


def find_sync_block(body: str, marker_id: str) -> re.Match | None:
    """Find a sync block by marker ID in the body text."""
    pattern = re.compile(
        rf'<!-- SYNC:{re.escape(marker_id)} -->\n(.*?)<!-- /SYNC:{re.escape(marker_id)} -->',
        re.DOTALL,
    )
    return pattern.search(body)


def replace_sync_block(body: str, marker_id: str, new_content: str) -> str:
    """Replace the content of an existing sync block."""
    pattern = re.compile(
        rf'<!-- SYNC:{re.escape(marker_id)} -->\n.*?<!-- /SYNC:{re.escape(marker_id)} -->',
        re.DOTALL,
    )
    replacement = f"<!-- SYNC:{marker_id} -->\n{new_content}\n<!-- /SYNC:{marker_id} -->"
    return pattern.sub(replacement, body)


def insert_sync_block(body: str, marker_id: str, content: str, after_heading: str | None = None) -> str:
    """Insert a new sync block after a specific heading, or at the top."""
    block = f"<!-- SYNC:{marker_id} -->\n{content}\n<!-- /SYNC:{marker_id} -->"

    if after_heading:
        idx = body.find(after_heading)
        if idx != -1:
            insert_pos = idx + len(after_heading)
            if insert_pos < len(body) and body[insert_pos] == '\n':
                insert_pos += 1
            return body[:insert_pos] + block + '\n' + body[insert_pos:]

    return block + '\n' + body


def upsert_sync_block(body: str, marker_id: str, content: str, after_heading: str | None = None) -> str:
    """Insert or update a sync block."""
    if find_sync_block(body, marker_id):
        return replace_sync_block(body, marker_id, content)
    return insert_sync_block(body, marker_id, content, after_heading)


# Common Korean surnames for person-name detection
_KOREAN_SURNAMES = set(
    '김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽성차주우구신임라진'
)


def is_korean_person_name(name: str) -> bool:
    """Check if a name looks like a Korean person name (2-3 pure Korean chars, starts with surname).

    Rejects mixed Korean+English names (these are concept entities, not people).
    """
    if not name or name.isascii():
        return False
    if ' ' in name or any(c.isascii() and not c.isspace() for c in name):
        return False
    korean_only = ''.join(c for c in name if '\uac00' <= c <= '\ud7a3')
    if not korean_only:
        return False
    return 2 <= len(korean_only) <= 3 and korean_only[0] in _KOREAN_SURNAMES


def create_stub_note(
    vault_root: Path,
    people_dir: str,
    entity_dir: str,
    entity_name: str,
    dry_run: bool = False,
) -> Path | None:
    """Create a minimal stub note for a discovered entity.

    Person names (2-4 char Korean with surname) go to people_dir.
    Other entities go to entity_dir.

    Returns the created path, or None if already exists.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Determine if person or general entity
    if is_korean_person_name(entity_name):
        note_dir = vault_root / people_dir
        frontmatter = {
            "type": "people",
            "tags": ["#type/people"],
            "index": ["[[🏷 People]]"],
        }
    else:
        note_dir = vault_root / entity_dir
        frontmatter = {
            "type": "entity",
            "tags": ["#type/entity"],
        }

    # Sanitize filename
    safe_name = re.sub(r'[/\\:*?"<>|]', '', entity_name).strip()
    note_path = note_dir / f"{safe_name}.md"

    if note_path.exists():
        return None

    if not dry_run:
        write_note(note_path, frontmatter, f"\n# {entity_name}\n\n")

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Created stub note: {note_path.name}")
    return note_path


def note_exists(path: Path) -> bool:
    return path.is_file()


def meeting_note_path(base_dir: Path, date_str: str, title: str) -> Path:
    """Generate meeting note path: YYYYMMDD_제목_Meeting.md"""
    safe_title = re.sub(r'[/\\:*?"<>|]', '', title).strip()
    safe_title = re.sub(r'\s+', ' ', safe_title)
    return base_dir / f"{date_str}_{safe_title}_Meeting.md"


def daily_note_path(base_dir: Path, date_str: str) -> Path:
    """Generate daily note path: YYYY-MM-DD.md"""
    return base_dir / f"{date_str}.md"
