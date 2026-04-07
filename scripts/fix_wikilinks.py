#!/usr/bin/env python3
"""Fix wikilink inconsistencies across the Obsidian vault.

Dry-run by default.  Pass --apply to execute.

Actions:
  Phase 0: Fix triple-bracket [[[  → [[  syntax errors
  Phase 1: Merge duplicate Term/entity files (keep canonical, delete dupe, rewrite links)
  Phase 2: Rewrite orphan short-form links to canonical form using VaultNameIndex
"""

from __future__ import annotations

import re
import sys
import tarfile
import unicodedata
from datetime import datetime
from pathlib import Path

from onlime.processors.name_resolver import VaultNameIndex, _WIKILINK_RE

VAULT = Path("~/Documents/Obsidian_sinc").expanduser()
BACKUP_DIR = Path("~/.onlime/backups").expanduser()
DRY_RUN = "--apply" not in sys.argv

# ── Phase 0: Triple-bracket fix ────────────────────────────────────────────
_TRIPLE_BRACKET_RE = re.compile(r"\[{3,}")


def phase0_fix_triple_brackets() -> int:
    """Fix [[[name]] → [[name]] across all vault files."""
    print("=== Phase 0: Fix triple brackets ===")
    count = 0
    for md in VAULT.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        new_text = _TRIPLE_BRACKET_RE.sub("[[", text)
        if new_text != text:
            fixes = len(_TRIPLE_BRACKET_RE.findall(text))
            rel = md.relative_to(VAULT)
            print(f"  FIX {rel} ({fixes} triple brackets)")
            count += fixes
            if not DRY_RUN:
                md.write_text(new_text, encoding="utf-8")
    print(f"  Total: {count} fixes\n")
    return count


# ── Phase 1: Merge duplicate entity files ──────────────────────────────────
# (old_stem, canonical_stem) — delete old, rewrite links to canonical
_DUPLICATE_PAIRS: list[tuple[str, str]] = [
    # Term dupes from audit
    ("앤스로픽 Anthropic", "앤트로픽 Anthropic"),
    ("해커톤 The Hackathon", "더해커톤 THEHACKATHON"),
    ("더해커톤 The Hackathon", "더해커톤 THEHACKATHON"),
    ("자동응답시스템 ARS", "자동응답 ARS"),
    ("스키마", "스키마 Schema"),
    ("에고 ego", "자아"),  # both 0-byte stubs
    # Typo variants
    ("더해커톤 THEHACKERTHON", "더해커톤 THEHACKATHON"),
]


def phase1_merge_duplicates() -> int:
    """Delete duplicate entity files and rewrite links to canonical form."""
    print("=== Phase 1: Merge duplicate files ===")
    count = 0
    for old_stem, canonical_stem in _DUPLICATE_PAIRS:
        # Find the old file
        old_files = list(VAULT.rglob(f"{old_stem}.md"))
        if not old_files:
            continue

        for old_file in old_files:
            rel = old_file.relative_to(VAULT)
            print(f"  DELETE {rel} → links rewrite to [[{canonical_stem}]]")
            if not DRY_RUN:
                old_file.unlink()

        # Rewrite links vault-wide
        pattern = re.compile(r"\[\[" + re.escape(old_stem) + r"(?=[\]|#])")
        replacement = f"[[{canonical_stem}"
        rewrites = _rewrite_pattern(pattern, replacement)
        count += rewrites

    print(f"  Total: {count} link rewrites\n")
    return count


# ── Phase 2: Rewrite short-form links to canonical ────────────────────────
# Explicit mapping for high-frequency orphan links that the name resolver
# might not catch (entity file doesn't exist or is ambiguous).
_EXPLICIT_REWRITES: dict[str, str] = {
    # Korean-only → canonical (from Term audit)
    "워크모어": "워크모어 Workmore",
    "리스크": "리스크 Concern",
    "더해커톤": "더해커톤 THEHACKATHON",
    "인공지능": "인공지능 AI",
    "AI": "인공지능 AI",
    "테슬라": "테슬라 Tesla",
    "낙관주의": "낙관주의 Optimism",
    "딥시크": "딥시크 DeepSeek",
    "본인인증": "본인인증 PASS",
    "프리미엄": "프리미엄 Freemium",
    "비즈카페": "비즈카페 BZCF",
    "링크드인 LinkedIn": "링크드인",
    # Casing fixes
    "폴리마켓 Polymarket": "폴리마켓 PolyMarket",
    "퍼플렉시티 perplexity": "퍼플렉시티 Perplexity",
    "워크모어 WorkMore": "워크모어 Workmore",
    "구글 GOOGLE": "구글 Google",
    # Philosophy names (from People audit)
    "니체": "프리드리히 니체",
    "니체 Nietzsche": "프리드리히 니체",
    "프리드리히 니체 Friedrich Nietzsche": "프리드리히 니체",
    "카프카": "프란츠 카프카",
    "하이데거": "마르틴 하이데거",
    "쇼펜하우어 Schopenhauer": "쇼펜하우어",
    # Korean+English mismatch (from People audit)
    "일론 머스크 Elon Musk": "일론 머스크",
    "블레즈 파스칼 Blaise Pascal": "블레즈 파스칼",
    "자크 라캉 Jacques Lacan": "자크 라캉",
    "빌 게이츠 Bill Gates": "빌 게이츠",
    # Old path prefixes
    "0. INPUT/People/박지웅": "박지웅",
}


def phase2_rewrite_orphan_links() -> int:
    """Rewrite known orphan/short-form links to canonical names."""
    print("=== Phase 2: Rewrite orphan links to canonical ===")
    total = 0
    for old_link, canonical in _EXPLICIT_REWRITES.items():
        pattern = re.compile(r"\[\[" + re.escape(old_link) + r"(?=[\]|#])")
        replacement = f"[[{canonical}"
        rewrites = _rewrite_pattern(pattern, replacement)
        if rewrites > 0:
            print(f"  [[{old_link}]] → [[{canonical}]] ({rewrites} files)")
            total += rewrites
    print(f"  Total: {total} file rewrites\n")
    return total


# ── Phase 3: Auto-resolve remaining links using VaultNameIndex ─────────────

def phase3_auto_resolve() -> int:
    """Use VaultNameIndex to find and fix remaining resolvable mismatches."""
    print("=== Phase 3: Auto-resolve via VaultNameIndex ===")
    idx = VaultNameIndex()
    idx.build(VAULT)

    total_files = 0
    # Scan content directories (where LLM-generated wikilinks live)
    content_dirs = [
        VAULT / "1.INPUT/Recording",
        VAULT / "1.INPUT/Media",
        VAULT / "1.INPUT/Article",
        VAULT / "1.INPUT/Inbox",
    ]
    for content_dir in content_dirs:
        if not content_dir.is_dir():
            continue
        for md in content_dir.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8")
            except Exception:
                continue

            seen: dict[str, str] = {}

            def _replace(m: re.Match) -> str:
                original = m.group(1).strip()
                if original in seen:
                    resolved = seen[original]
                else:
                    resolved = idx.match(original) or original
                    seen[original] = resolved
                if resolved == original:
                    return m.group(0)
                full = m.group(0)
                old_target = m.group(1)
                return full.replace(f"[[{old_target}", f"[[{resolved}", 1)

            new_text = _WIKILINK_RE.sub(_replace, text)
            if new_text != text:
                changes = sum(1 for k, v in seen.items() if k != v)
                rel = md.relative_to(VAULT)
                print(f"  RESOLVE {rel} ({changes} links)")
                total_files += 1
                if not DRY_RUN:
                    md.write_text(new_text, encoding="utf-8")

    print(f"  Total: {total_files} files\n")
    return total_files


# ── Helpers ────────────────────────────────────────────────────────────────

def _rewrite_pattern(pattern: re.Pattern, replacement: str) -> int:
    """Rewrite a regex pattern across all vault .md files. Returns count of files changed."""
    count = 0
    for md in VAULT.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        new_text = pattern.sub(replacement, text)
        if new_text != text:
            count += 1
            if not DRY_RUN:
                md.write_text(new_text, encoding="utf-8")
    return count


def main() -> None:
    print(f"Vault: {VAULT}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'APPLY'}\n")

    if not DRY_RUN:
        # Create backup
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"pre_wikilink_fix_{datetime.now():%Y%m%d_%H%M%S}.tar.gz"
        print(f"Creating backup... (this may take a moment)")
        # Only backup the files we might modify (not the entire vault)
        with tarfile.open(backup_path, "w:gz") as tar:
            for d in ["1.INPUT", "2.OUTPUT"]:
                dir_path = VAULT / d
                if dir_path.exists():
                    tar.add(dir_path, arcname=d)
        print(f"Backup: {backup_path}\n")

    p0 = phase0_fix_triple_brackets()
    p1 = phase1_merge_duplicates()
    p2 = phase2_rewrite_orphan_links()
    p3 = phase3_auto_resolve()

    print(f"=== Summary ===")
    print(f"  Phase 0 (triple brackets): {p0} fixes")
    print(f"  Phase 1 (merge dupes):     {p1} link rewrites")
    print(f"  Phase 2 (orphan links):    {p2} file rewrites")
    print(f"  Phase 3 (auto-resolve):    {p3} files")

    if DRY_RUN:
        print("\nPass --apply to execute.")


if __name__ == "__main__":
    main()
