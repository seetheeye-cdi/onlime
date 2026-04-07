#!/usr/bin/env python3
"""Migrate 1.INPUT/Meeting/ files into 1.INPUT/Recording/ with unified naming.

Dry-run by default.  Pass --apply to execute.

Actions:
  - Delete empty stubs (≤ 2 bytes)
  - Rename to  {topic}-음성-대면.md  format
  - Rewrite frontmatter to Recording schema
  - Move to 1.INPUT/Recording/
  - Rewrite wikilinks across the vault
"""

from __future__ import annotations

import os
import re
import sys
import tarfile
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml

# ── paths ──────────────────────────────────────────────────────────────────
VAULT = Path("~/Documents/Obsidian_sinc").expanduser()
MEETING_DIR = VAULT / "1.INPUT/Meeting"
RECORDING_DIR = VAULT / "1.INPUT/Recording"
BACKUP_DIR = Path("~/.onlime/backups").expanduser()

DRY_RUN = "--apply" not in sys.argv

# ── filename parsing helpers ───────────────────────────────────────────────
DATE_PREFIX_RE = re.compile(r"^(\d{8})_")
MM_DD_PREFIX_RE = re.compile(r"^(\d{2}-\d{2})\s+")
PARTICIPANTS_TOPIC_RE = re.compile(r"^(.+?)\s+[-–—]\s+(.+)$")
SUFFIX_RE = re.compile(r"[_\s]*(Meeting|Plaud|meeting|plaud)$")
FORBIDDEN_RE = re.compile(r'[?":*|<>\\]')
TIMESTAMP_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{6}$")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def sanitize(title: str, max_length: int = 80) -> str:
    clean = FORBIDDEN_RE.sub(" ", title)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_length:
        clean = clean[:max_length].rsplit(" ", 1)[0]
    return clean.rstrip(". ")


def extract_topic_and_meta(stem: str) -> tuple[str, list[str], str | None]:
    """Return (topic, participants, date_YYYYMMDD | None)."""
    stem = nfc(stem)

    # Strip _Meeting / _Plaud suffix
    stem = SUFFIX_RE.sub("", stem).strip()

    # Extract date prefix
    date_str: str | None = None
    m = DATE_PREFIX_RE.match(stem)
    if m:
        date_str = m.group(1)
        stem = stem[m.end():]

    # Strip redundant MM-DD prefix (e.g. "03-19 ")
    m = MM_DD_PREFIX_RE.match(stem)
    if m:
        stem = stem[m.end():]

    # Check for "participants - topic" pattern
    participants: list[str] = []
    m = PARTICIPANTS_TOPIC_RE.match(stem)
    if m:
        part_str = m.group(1).strip()
        topic = m.group(2).strip()
        participants = [p.strip() for p in re.split(r"[·,]", part_str) if p.strip()]
    else:
        topic = stem.strip()

    # If topic is just a timestamp like "2026-03-21 153617", treat as empty
    if TIMESTAMP_ONLY_RE.match(topic):
        topic = ""

    # Truncate long topics to ~25 chars at word boundary
    if len(topic) > 25:
        cut = topic[:25]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        topic = cut

    return topic, participants, date_str


def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    fm_str = content[3:end].strip()
    try:
        fm = yaml.safe_load(fm_str) or {}
    except Exception:
        fm = {}
    body = content[end + 3:].lstrip("\n")
    return fm, body


def build_new_content(
    old_fm: dict,
    body: str,
    new_title: str,
    participants: list[str],
    date_str: str | None,
) -> str:
    new_fm: dict = {}

    # ID
    if old_fm.get("plaud_id"):
        new_fm["id"] = f"plaud:{old_fm['plaud_id']}"
    elif old_fm.get("id"):
        new_fm["id"] = old_fm["id"]

    new_fm["title"] = new_title

    # Created date
    created = old_fm.get("created", "")
    if not created and date_str:
        try:
            dt = datetime.strptime(date_str, "%Y%m%d")
            created = dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    new_fm["created"] = str(created) if created else ""

    # Tags
    tags = old_fm.get("tags", [])
    new_fm["tags"] = tags if isinstance(tags, list) else []

    # People — prefer existing participants, fall back to parsed ones
    people = old_fm.get("participants", [])
    if not people and participants:
        people = [f"[[{p}]]" for p in participants]
    if people:
        new_fm["people"] = people

    new_fm["category"] = "1.INPUT/Recording"

    if old_fm.get("source"):
        new_fm["source"] = old_fm["source"]
    if old_fm.get("plaud_id"):
        new_fm["plaud_id"] = old_fm["plaud_id"]

    fm_str = yaml.dump(
        new_fm, allow_unicode=True, default_flow_style=False, sort_keys=False,
    )
    return f"---\n{fm_str}---\n\n{body}"


# ── wikilink rewriting ─────────────────────────────────────────────────────
def rewrite_wikilinks(
    renames: dict[str, str],  # old_stem → new_stem
) -> int:
    """Rewrite [[old_stem]] → [[new_stem]] across the vault. Returns count."""
    # Build regex: match [[old_stem]] or [[old_stem|alias]] or [[old_stem#heading]]
    if not renames:
        return 0

    patterns: list[tuple[re.Pattern, str]] = []
    for old, new in renames.items():
        # Escape for regex, use lookahead to catch ]], |, #
        pat = re.compile(r"\[\[" + re.escape(old) + r"(?=[\]|#])")
        patterns.append((pat, f"[[{new}"))

    count = 0
    for md_file in VAULT.rglob("*.md"):
        # Skip Meeting dir (files being moved) and Recording dir (new files)
        if MEETING_DIR in md_file.parents:
            continue
        if RECORDING_DIR in md_file.parents:
            continue

        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        new_text = text
        for pat, replacement in patterns:
            new_text = pat.sub(replacement, new_text)

        if new_text != text:
            if DRY_RUN:
                changed = sum(1 for p, _ in patterns if p.search(text))
                print(f"  REWRITE {md_file.relative_to(VAULT)} ({changed} links)")
            else:
                md_file.write_text(new_text, encoding="utf-8")
                print(f"  Rewrote {md_file.relative_to(VAULT)}")
            count += 1

    return count


# ── main ───────────────────────────────────────────────────────────────────
def main() -> None:
    if not MEETING_DIR.exists():
        print(f"Meeting dir not found: {MEETING_DIR}")
        sys.exit(1)

    files = sorted(
        [f for f in MEETING_DIR.iterdir() if f.suffix == ".md" and f.name != ".DS_Store"],
        key=lambda f: f.name,
    )
    print(f"Found {len(files)} Meeting files")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'APPLY'}\n")

    deletes: list[Path] = []
    moves: list[tuple[Path, Path, str, list[str], str | None]] = []
    renames: dict[str, str] = {}  # old_stem → new_stem
    seen_targets: dict[str, Path] = {}

    for f in files:
        size = f.stat().st_size
        stem = nfc(f.stem)

        # Delete empty/stub files
        if size <= 2:
            deletes.append(f)
            continue

        topic, participants, date_str = extract_topic_and_meta(stem)

        # Fallback topic: use filename stem if extraction gave nothing useful
        if not topic or len(topic) < 2:
            # Try reading H1 from content
            try:
                content = f.read_text(encoding="utf-8")
                h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
                if h1_match:
                    topic = h1_match.group(1).strip()[:25]
                else:
                    topic = stem[:25]
            except Exception:
                topic = stem[:25]

        clean_topic = sanitize(topic)
        new_name = f"{clean_topic}-음성-대면.md"

        # Handle duplicate target names
        if new_name in seen_targets:
            if date_str:
                new_name = f"{clean_topic} {date_str}-음성-대면.md"
            if new_name in seen_targets:
                i = 2
                base_topic = clean_topic
                while new_name in seen_targets:
                    new_name = f"{base_topic} ({i})-음성-대면.md"
                    i += 1

        seen_targets[new_name] = f
        target = RECORDING_DIR / new_name
        moves.append((f, target, topic, participants, date_str))
        renames[stem] = target.stem

    # ── report ─────────────────────────────────────────────────────────────
    print(f"=== Deletes: {len(deletes)} ===")
    for d in deletes:
        print(f"  DEL {d.name} ({d.stat().st_size}b)")

    print(f"\n=== Moves: {len(moves)} ===")
    for src, dst, topic, parts, date in moves:
        print(f"  {src.name}")
        print(f"    → {dst.name}")

    print(f"\n=== Wikilink rewrites ===")
    link_count = rewrite_wikilinks(renames)
    print(f"  {link_count} files would be rewritten\n")

    if DRY_RUN:
        print("Pass --apply to execute.")
        return

    # ── backup ─────────────────────────────────────────────────────────────
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"meeting_migration_{datetime.now():%Y%m%d_%H%M%S}.tar.gz"
    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(MEETING_DIR, arcname="Meeting")
    print(f"Backup: {backup_path}")

    # ── execute ────────────────────────────────────────────────────────────
    RECORDING_DIR.mkdir(parents=True, exist_ok=True)

    for d in deletes:
        d.unlink()
        print(f"Deleted: {d.name}")

    for src, dst, topic, participants, date_str in moves:
        content = src.read_text(encoding="utf-8")
        old_fm, body = parse_frontmatter(content)
        new_title = dst.stem
        new_content = build_new_content(old_fm, body, new_title, participants, date_str)

        dst.write_text(new_content, encoding="utf-8")
        src.unlink()
        print(f"Moved: {src.name} → {dst.name}")

    # Rewrite wikilinks (already computed, now apply)
    rewrite_wikilinks(renames)

    # Remove empty Meeting dir
    remaining = list(MEETING_DIR.iterdir())
    remaining = [r for r in remaining if r.name != ".DS_Store"]
    if not remaining:
        # Remove .DS_Store if present
        ds = MEETING_DIR / ".DS_Store"
        if ds.exists():
            ds.unlink()
        MEETING_DIR.rmdir()
        print(f"\nRemoved empty directory: {MEETING_DIR.relative_to(VAULT)}")

    print(f"\nDone! {len(deletes)} deleted, {len(moves)} moved.")


if __name__ == "__main__":
    main()
