"""Strip emoji prefix from H1 headings in People .md files.

Phase 2a renamed all `👤X.md` / `🙍‍♂️X.md` files to `X.md`, but the H1
headings inside the files (`# 🙍‍♂️X`) were not touched. This script does
that cleanup as a follow-up.

Safe because:
  - only rewrites lines matching `^# (👤|🙍‍♂️|🙍)\s*` at the START of a line
  - preserves the rest of the heading (the actual name)
  - no link impact (H1 text is not part of any wikilink resolution)

Usage:
  python scripts/vault_h1_emoji_sweep.py            # dry-run
  python scripts/vault_h1_emoji_sweep.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")

# Match `# ` + emoji (👤, 🙍‍♂️ with ZWJ, or bare 🙍) at line start.
H1_EMOJI = re.compile(r"^(#+)\s*(?:👤|🙍‍♂️|🙍)\s*", re.MULTILINE)


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
        new_text, n = H1_EMOJI.subn(r"\1 ", text)
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
    print(f"[{mode}] {files} files touched, {total} H1 headings cleaned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
