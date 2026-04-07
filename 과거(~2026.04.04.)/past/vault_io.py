"""Obsidian markdown file I/O: frontmatter parsing, sync block management."""
from __future__ import annotations

import re
import yaml
from pathlib import Path
from typing import Optional, Tuple

FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
SYNC_BLOCK_RE = re.compile(
    r'<!-- SYNC:(\S+) -->\n(.*?)<!-- /SYNC:\1 -->',
    re.DOTALL
)


def read_note(path: Path) -> Tuple[dict, str]:
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


def write_note(path: Path, frontmatter: dict, body: str):
    """Write frontmatter + body back to an Obsidian note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
    content = f"---\n{fm_str}---\n{body}"
    # Atomic write: write to tmp then rename
    tmp = path.with_suffix('.tmp')
    tmp.write_text(content, encoding='utf-8')
    tmp.rename(path)


def find_sync_block(body: str, marker_id: str) -> re.Match | None:
    """Find a sync block by marker ID in the body text."""
    pattern = re.compile(
        rf'<!-- SYNC:{re.escape(marker_id)} -->\n(.*?)<!-- /SYNC:{re.escape(marker_id)} -->',
        re.DOTALL
    )
    return pattern.search(body)


def replace_sync_block(body: str, marker_id: str, new_content: str) -> str:
    """Replace the content of an existing sync block."""
    pattern = re.compile(
        rf'<!-- SYNC:{re.escape(marker_id)} -->\n.*?<!-- /SYNC:{re.escape(marker_id)} -->',
        re.DOTALL
    )
    replacement = f"<!-- SYNC:{marker_id} -->\n{new_content}\n<!-- /SYNC:{marker_id} -->"
    return pattern.sub(replacement, body)


def insert_sync_block(body: str, marker_id: str, content: str, after_heading: str = None) -> str:
    """Insert a new sync block after a specific heading, or at the top."""
    block = f"<!-- SYNC:{marker_id} -->\n{content}\n<!-- /SYNC:{marker_id} -->"

    if after_heading:
        # Find the heading and insert after it (and its immediate newline)
        idx = body.find(after_heading)
        if idx != -1:
            insert_pos = idx + len(after_heading)
            # Skip past the newline after the heading
            if insert_pos < len(body) and body[insert_pos] == '\n':
                insert_pos += 1
            return body[:insert_pos] + block + '\n' + body[insert_pos:]

    # Fallback: insert at the very top
    return block + '\n' + body


def upsert_sync_block(body: str, marker_id: str, content: str, after_heading: str = None) -> str:
    """Insert or update a sync block."""
    if find_sync_block(body, marker_id):
        return replace_sync_block(body, marker_id, content)
    return insert_sync_block(body, marker_id, content, after_heading)


def note_exists(path: Path) -> bool:
    return path.is_file()


def meeting_note_path(base_dir: Path, date_str: str, title: str) -> Path:
    """Generate meeting note path: YYYYMMDD_제목_Meeting.md"""
    # Sanitize title for filename
    safe_title = re.sub(r'[/\\:*?"<>|]', '', title).strip()
    safe_title = re.sub(r'\s+', ' ', safe_title)
    return base_dir / f"{date_str}_{safe_title}_Meeting.md"


def daily_note_path(base_dir: Path, date_str: str) -> Path:
    """Generate daily note path: YYYY-MM-DD.md"""
    return base_dir / f"{date_str}.md"
