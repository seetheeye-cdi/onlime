#!/usr/bin/env python3
"""Rename vault files whose names contain characters that Obsidian Sync
refuses on Android/iOS (?, ", :, *, |, <, >).

Usage:
    .venv/bin/python3 scripts/sanitize_vault_filenames.py [--apply]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAULT_ROOT = Path.home() / "Documents" / "Obsidian_sinc"

# Characters Obsidian Sync refuses on mobile filesystems.
_FORBIDDEN = re.compile(r'[?"*|<>:\\]')
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize(name: str) -> str:
    # Strip control characters.
    cleaned = _CTRL.sub("", name)
    # Replace forbidden punctuation with a single space (preserves word breaks).
    cleaned = _FORBIDDEN.sub(" ", cleaned)
    # Collapse runs of whitespace introduced by replacement.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Windows / Obsidian Sync refuses trailing dots/spaces in basenames.
    stem, dot, ext = cleaned.rpartition(".")
    if not dot:  # no extension somehow; just trim
        return cleaned.rstrip(" .")
    stem = stem.rstrip(" .")
    if not stem:
        return ""
    return f"{stem}.{ext}"


def _needs_rename(name: str) -> bool:
    if _FORBIDDEN.search(name) or _CTRL.search(name):
        return True
    # foo..md, foo .md, etc. — trailing dot/space in the stem.
    stem, dot, _ = name.rpartition(".")
    if dot and (stem.endswith(".") or stem.endswith(" ")):
        return True
    return False


def _unique(path: Path) -> Path:
    """Append a numeric suffix if the target already exists."""
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    i = 2
    while True:
        candidate = path.with_name(f"{stem} ({i}){ext}")
        if not candidate.exists():
            return candidate
        i += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually rename files")
    parser.add_argument("--root", type=Path, default=VAULT_ROOT)
    args = parser.parse_args()

    root: Path = args.root.expanduser()
    if not root.is_dir():
        print(f"Vault not found: {root}", file=sys.stderr)
        return 1

    renames: list[tuple[Path, Path]] = []
    for p in root.rglob("*.md"):
        # Skip .trash and any hidden dirs.
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        if not _needs_rename(p.name):
            continue
        new_name = _sanitize(p.name)
        if new_name == p.name or not new_name:
            continue
        new_path = _unique(p.with_name(new_name))
        renames.append((p, new_path))

    if not renames:
        print("Nothing to rename.")
        return 0

    for old, new in renames:
        print(f"  {old.relative_to(root)}  ->  {new.relative_to(root)}")
    print(f"\n{len(renames)} file(s) to rename.")

    if not args.apply:
        print("\n(dry run — rerun with --apply to rename)")
        return 0

    for old, new in renames:
        old.rename(new)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
