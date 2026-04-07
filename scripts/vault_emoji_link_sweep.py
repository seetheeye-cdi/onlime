"""Global wikilink sweep: strip emoji prefixes from all [[👤X]] / [[🙍‍♂️X]] links.

Run AFTER all emoji-prefixed files have been removed from the vault.
This catches stale links whose target file was never in 1.INPUT/People/
(e.g. files that lived in 2.OUTPUT/People/Network from the start).

Usage:
  python scripts/vault_emoji_link_sweep.py             # dry-run
  python scripts/vault_emoji_link_sweep.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")

# Match [[👤X]] or [[👤X|...]] or [[👤X#...]]
# and similarly for 🙍‍♂️ (with ZWJ) or bare 🙍.
PATTERN = re.compile(r"\[\[(?:👤|🙍‍♂️|🙍)\s*")


def sweep(apply: bool) -> tuple[int, int]:
    files_touched = 0
    total = 0
    for md in VAULT_ROOT.rglob("*.md"):
        if any(part.startswith(".") for part in md.relative_to(VAULT_ROOT).parts):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text, n = PATTERN.subn("[[", text)
        if n == 0:
            continue
        files_touched += 1
        total += n
        if apply:
            try:
                md.write_text(new_text, encoding="utf-8")
            except OSError as exc:
                print(f"write failed: {md} ({exc})", file=sys.stderr)
    return files_touched, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    files, total = sweep(apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {files} files touched, {total} links rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
