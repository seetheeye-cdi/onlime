"""Retroactively apply one-sentence-per-line formatting to existing ## 요약 sections.

Phase 2b+ applied `format_one_sentence_per_line()` to the summarizer output,
but notes generated BEFORE that code change still have summary sections as
walls of text. This script walks the vault, finds every `## 요약` section,
and rewrites it in place using the same formatter.

Safe: only touches text BETWEEN `## 요약\n` and the next `## ` header (or EOF).
Other sections (대본 전문, 영상 설명, frontmatter, etc.) are untouched.

Usage:
  python scripts/vault_format_summaries.py            # dry-run
  python scripts/vault_format_summaries.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")

# Match the ## 요약 section, capturing its body up to the next ## header or EOF.
# Group 1 = header line incl trailing newline, group 2 = body, group 3 = next header or end.
_SUMMARY_RE = re.compile(
    r"(^## 요약\s*\n)(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)

# Sentence splitter (mirrors processors/summarizer.py::_SENTENCE_SPLIT_RE)
_SENTENCE_SPLIT_RE = re.compile(r"([.!?。！？])[ \t]+(?=\S)")


def format_one_sentence_per_line(text: str) -> str:
    if not text:
        return ""
    out_lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            out_lines.append(line)
            continue
        expanded = _SENTENCE_SPLIT_RE.sub(r"\1\n", line)
        out_lines.extend(expanded.split("\n"))
    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def process_file(md: Path, apply: bool) -> tuple[bool, int]:
    """Return (changed, n_sentences_added) for this file."""
    try:
        text = md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return (False, 0)

    match = _SUMMARY_RE.search(text)
    if not match:
        return (False, 0)

    header = match.group(1)
    body = match.group(2)

    formatted = format_one_sentence_per_line(body)
    if not formatted:
        return (False, 0)

    # Count new sentences inserted (heuristic: newlines added)
    added = formatted.count("\n") - body.count("\n")

    if formatted == body.strip():
        return (False, 0)

    # Preserve the single trailing blank line before the next section
    new_section = f"{header}{formatted}\n\n"
    new_text = text[: match.start()] + new_section + text[match.end():]

    if apply:
        try:
            md.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            print(f"write failed: {md} ({exc})", file=sys.stderr)
            return (False, 0)

    return (True, max(0, added))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not VAULT_ROOT.is_dir():
        print(f"vault not found: {VAULT_ROOT}", file=sys.stderr)
        return 2

    changed_files: list[Path] = []
    total_added = 0
    for md in VAULT_ROOT.rglob("*.md"):
        if any(part.startswith(".") for part in md.relative_to(VAULT_ROOT).parts):
            continue
        changed, added = process_file(md, apply=args.apply)
        if changed:
            changed_files.append(md)
            total_added += added

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {len(changed_files)} files with reformatted ## 요약 sections")
    print(f"        +{total_added} new line breaks (approx)")
    print()
    for md in changed_files[:20]:
        print(f"   ✓ {md.relative_to(VAULT_ROOT)}")
    if len(changed_files) > 20:
        print(f"   … {len(changed_files) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
