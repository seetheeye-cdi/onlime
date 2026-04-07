"""Retroactively proofread existing ## 대본 전문 sections via Claude.

Pre-existing notes created before transcript_proofreader was wired in still
contain raw YouTube auto-caption transcripts: walls of text, ASR errors, no
punctuation. This script walks the vault, locates every `## 대본 전문` section,
runs it through `proofread_transcript()`, and rewrites the section in place.

Usage:
  python scripts/vault_proofread_transcripts.py            # dry-run
  python scripts/vault_proofread_transcripts.py --apply
  python scripts/vault_proofread_transcripts.py --apply --only "후회만"

Notes:
- Only touches the ## 대본 전문 section body (between that header and the next `## `).
- Frontmatter, ## 요약, ## 영상 설명, etc. are untouched.
- Creates a .bak backup beside each modified file on --apply.
- Skips files where the transcript is already one-sentence-per-line (heuristic:
  avg line length < 80 chars AND > 80% of lines end in sentence-ending punctuation).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onlime.processors.transcript_proofreader import proofread_transcript  # noqa: E402

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")

# Capture the body of ## 대본 전문 up to the next ## header or EOF.
_TRANSCRIPT_RE = re.compile(
    r"(^## 대본 전문\s*\n)(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)

_SENTENCE_END = re.compile(r"[.!?。！？]\s*$")


def _already_formatted(body: str) -> bool:
    """Heuristic: consider a transcript 'already clean' if its lines look
    like short punctuated sentences."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        return True
    avg = sum(len(ln) for ln in lines) / len(lines)
    punctuated = sum(1 for ln in lines if _SENTENCE_END.search(ln))
    ratio = punctuated / len(lines)
    return avg < 80 and ratio > 0.8


async def process_file(md: Path, apply: bool) -> tuple[bool, int, int]:
    """Return (changed, in_chars, out_chars)."""
    try:
        text = md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return (False, 0, 0)

    match = _TRANSCRIPT_RE.search(text)
    if not match:
        return (False, 0, 0)

    header = match.group(1)
    body = match.group(2).strip()

    if not body:
        return (False, 0, 0)
    if _already_formatted(body):
        return (False, len(body), len(body))

    corrected = await proofread_transcript(body)
    if not corrected or corrected.strip() == body.strip():
        return (False, len(body), len(corrected))

    new_section = f"{header}{corrected}\n\n"
    new_text = text[: match.start()] + new_section + text[match.end():]

    if apply:
        try:
            bak = md.with_suffix(md.suffix + ".bak")
            bak.write_text(text, encoding="utf-8")
            md.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            print(f"write failed: {md} ({exc})", file=sys.stderr)
            return (False, len(body), len(corrected))

    return (True, len(body), len(corrected))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--only", help="Substring filter on file stem")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    args = parser.parse_args()

    if not VAULT_ROOT.is_dir():
        print(f"vault not found: {VAULT_ROOT}", file=sys.stderr)
        return 2

    # Discovery phase: find candidate files.
    candidates: list[Path] = []
    for md in VAULT_ROOT.rglob("*.md"):
        if any(part.startswith(".") for part in md.relative_to(VAULT_ROOT).parts):
            continue
        if args.only and args.only not in md.stem:
            continue
        try:
            head = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "## 대본 전문" not in head:
            continue
        candidates.append(md)

    if args.limit:
        candidates = candidates[: args.limit]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {len(candidates)} candidate files with ## 대본 전문")
    print()

    changed_files: list[Path] = []
    total_in = 0
    total_out = 0

    for i, md in enumerate(candidates, start=1):
        rel = md.relative_to(VAULT_ROOT)
        print(f"[{i}/{len(candidates)}] {rel}")
        try:
            changed, in_chars, out_chars = await process_file(md, apply=args.apply)
        except Exception as exc:
            print(f"   ! error: {exc}")
            continue
        if changed:
            changed_files.append(md)
            total_in += in_chars
            total_out += out_chars
            print(f"   ✓ {in_chars} → {out_chars} chars")
        else:
            if in_chars == 0:
                print("   — no transcript section body")
            elif in_chars == out_chars:
                print("   — already formatted (skipped)")
            else:
                print("   — no change")

    print()
    print(f"[{mode}] {len(changed_files)} files modified")
    print(f"        {total_in} → {total_out} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
