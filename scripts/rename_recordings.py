#!/usr/bin/env python3
"""Rename existing recording notes to '{주제}-음성-{통화|메모}' convention.

Uses Claude Haiku to generate topic from transcript.

Usage:
    python scripts/rename_recordings.py           # dry-run (no LLM)
    python scripts/rename_recordings.py --apply   # execute renames (calls LLM)
"""
from __future__ import annotations

import asyncio
import re
import sys
import unicodedata
from pathlib import Path

RECORDING_DIR = Path("~/Documents/Obsidian_sinc/1.INPUT/Recording").expanduser()

# Samsung call filename pattern
_SAMSUNG_CALL_RE = re.compile(r"^통화\s+")


def _read_frontmatter_field(content: str, field: str) -> str:
    """Extract a field value from YAML frontmatter."""
    m = re.search(rf"^{field}:\s*'?(.+?)'?\s*$", content, re.MULTILINE)
    if not m:
        return ""
    # macOS uses NFD for filenames; normalize to NFC for regex matching
    return unicodedata.normalize("NFC", m.group(1).strip("'\" "))


def _read_transcript(content: str) -> str:
    """Extract transcript from ## 전사 전문 section."""
    m = re.search(r"## 전사 전문\s*\n+([\s\S]+?)(?=\n## |\Z)", content)
    return m.group(1).strip() if m else ""


def _detect_type(file_name: str) -> str:
    """Detect 통화 or 메모 from original audio filename."""
    if _SAMSUNG_CALL_RE.match(file_name):
        return "통화"
    return "메모"


def _extract_contact(file_name: str) -> str | None:
    """Extract contact from Samsung call filename."""
    m = re.match(r"^통화\s+(.+?)_\d{6}_\d{6}\.m4a$", file_name)
    return m.group(1).strip() if m else None


def _sanitize(title: str) -> str:
    """Remove Obsidian-forbidden chars."""
    for ch in '?":|<>\\*':
        title = title.replace(ch, "")
    return title.strip().rstrip(".")


async def _generate_topic(transcript: str) -> str:
    """Call Claude Haiku to generate a ~15 char topic."""
    # Lazy import to avoid loading everything in dry-run
    from onlime.processors.summarizer import generate_title
    topic = await generate_title(transcript)
    return topic.strip().strip('"\'')


def _collect_files() -> list[dict]:
    """Collect all recording files and their metadata."""
    files = sorted(RECORDING_DIR.glob("*.md"))
    results = []
    for f in files:
        content = f.read_text(encoding="utf-8")
        file_name = _read_frontmatter_field(content, "file_name")
        transcript = _read_transcript(content)
        rec_type = _detect_type(file_name)
        contact = _extract_contact(file_name) if rec_type == "통화" else None
        results.append({
            "path": f,
            "content": content,
            "file_name": file_name,
            "transcript": transcript,
            "rec_type": rec_type,
            "contact": contact,
        })
    return results


async def _apply_renames(entries: list[dict]) -> None:
    """Generate titles via LLM and rename files."""
    for entry in entries:
        transcript = entry["transcript"]
        if not transcript or len(transcript) < 50:
            topic = "녹음"
        else:
            topic = await _generate_topic(transcript)
            if not topic:
                topic = "녹음"

        new_title = f"{topic}-음성-{entry['rec_type']}"
        new_title = _sanitize(new_title)
        new_path = entry["path"].parent / f"{new_title}.md"

        # Handle collision
        if new_path.exists() and new_path != entry["path"]:
            suffix = 2
            while True:
                new_path = entry["path"].parent / f"{new_title} ({suffix}).md"
                if not new_path.exists():
                    break
                suffix += 1

        if new_path == entry["path"]:
            print(f"  SKIP (already correct): {entry['path'].name}")
            continue

        content = entry["content"]
        # Update frontmatter title
        content = re.sub(
            r"^title:\s*.+$",
            f"title: '{new_title}'",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        # Update H1 heading
        content = re.sub(
            r"^# .+$",
            f"# {new_title}",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        # Add people to frontmatter if contact and not already present
        if entry["contact"] and "people:" not in content:
            contact = entry["contact"]
            people_line = f"title: '{new_title}'\npeople:\n- '[[{contact}]]'"
            content = content.replace(f"title: '{new_title}'", people_line, 1)

        new_path.write_text(content, encoding="utf-8")
        entry["path"].unlink()
        print(f"  OK: {entry['path'].name}")
        print(f"    → {new_path.name}")

    print(f"\nDone.")


def main() -> None:
    apply = "--apply" in sys.argv

    if not RECORDING_DIR.exists():
        print(f"Recording dir not found: {RECORDING_DIR}")
        return

    entries = _collect_files()
    if not entries:
        print("No files found.")
        return

    print(f"Found {len(entries)} recording notes:\n")
    for e in entries:
        print(f"  {e['path'].name}")
        print(f"    file_name: {e['file_name']}")
        print(f"    type: {e['rec_type']}, contact: {e['contact']}")
        print(f"    transcript: {len(e['transcript'])} chars")

    if not apply:
        print(f"\nDry run. Use --apply to rename with LLM-generated titles.")
        return

    print(f"\nGenerating titles and renaming...")
    asyncio.run(_apply_renames(entries))


if __name__ == "__main__":
    main()
