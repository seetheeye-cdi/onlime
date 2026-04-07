"""Phase 2b vault cleanup — merge INPUT↔OUTPUT People pair duplicates.

Discovered by Phase 2b research agent: 20 pairs where the same person has
a file in `1.INPUT/People/` AND in `2.OUTPUT/People/{Network,Active}/`.

Per-pair strategy (hardcoded after manual inspection 2026-04-06):

  "use_input"    — INPUT has rich body, OUTPUT is a stub placeholder.
                   Replace OUTPUT content with INPUT content, delete INPUT.
                   Canonical location = existing OUTPUT path.
  "delete_input" — Files are identical (or INPUT is empty/duplicate stub).
                   Delete INPUT, keep OUTPUT.

Special case: 김영진
  - 1.INPUT/People/김영진_프로필.md        → rich profile (2181B)
  - 1.INPUT/People/김영진_한성 7기.md      → stub redirect `[[김영진_프로필]]`
  - 2.OUTPUT/People/Network/김영진(한성 7기).md → stub redirect
  Strategy: write 프로필 content into OUTPUT canonical, delete both INPUTs.
  Also rewrite `[[김영진_한성 7기]]` → `[[김영진(한성 7기)]]` across vault.

Usage:
  python scripts/vault_cleanup_phase2b.py           # dry-run
  python scripts/vault_cleanup_phase2b.py --apply   # apply for real
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
BACKUP_DIR = Path.home() / ".onlime" / "backups"


@dataclass
class Pair:
    input_rel: str
    output_rel: str
    action: str  # "use_input" | "delete_input"


# Ordered by discovery pass. Action chosen after reading each pair.
PAIRS: list[Pair] = [
    Pair("1.INPUT/People/권민재_한성 6기, 프린스턴 컴공, 알레프랩.md",
         "2.OUTPUT/People/Network/권민재_프린스턴 컴공_알레프랩.md", "use_input"),
    Pair("1.INPUT/People/김동희_한성 6기, 서울대 전기정보, 포커.md",
         "2.OUTPUT/People/Network/김동희(한성 6기)_개발_포커.md", "use_input"),
    Pair("1.INPUT/People/김민재_참치상사, 개발.md",
         "2.OUTPUT/People/Network/김민재_참치상사 개발자.md", "delete_input"),
    # 김영진 rich profile → overwrite OUTPUT, delete INPUT
    Pair("1.INPUT/People/김영진_프로필.md",
         "2.OUTPUT/People/Network/김영진(한성 7기).md", "use_input"),
    # 김영진 stub redirect → just delete INPUT (OUTPUT already has content after previous step)
    Pair("1.INPUT/People/김영진_한성 7기.md",
         "2.OUTPUT/People/Network/김영진(한성 7기).md", "delete_input"),
    Pair("1.INPUT/People/김예지_한성 5기, 서울대컴공-경희대의대, 의료데이터.md",
         "2.OUTPUT/People/Network/김예지(한성 5기).md", "use_input"),
    Pair("1.INPUT/People/김욱영_이어드림, 더해커톤 개발, 에이아이당 개발.md",
         "2.OUTPUT/People/Network/김욱영.md", "use_input"),
    Pair("1.INPUT/People/김유신_한성 6기, 전기정보.md",
         "2.OUTPUT/People/Network/김유신(한성 6기)_전기정보.md", "use_input"),
    Pair("1.INPUT/People/김지민_한성 3기.md",
         "2.OUTPUT/People/Network/김지민(한성 3기).md", "use_input"),
    Pair("1.INPUT/People/김현준_더해커톤, 고3앱스토어1위, 개발자리워드.md",
         "2.OUTPUT/People/Network/김현준_Skrr_머니워크_바이럴.md", "use_input"),
    Pair("1.INPUT/People/나정현_한성 3기, PD, 영상.md",
         "2.OUTPUT/People/Active/나정현(한성 3기)_PD, 영상.md", "use_input"),
    Pair("1.INPUT/People/박하나_토스페이먼츠, 매니저.md",
         "2.OUTPUT/People/Network/박하나_토스 페이먼츠 매니저.md", "delete_input"),
    Pair("1.INPUT/People/박혜민_뉴웨이즈 대표, 채용.md",
         "2.OUTPUT/People/Network/박혜민_뉴웨이즈 대표.md", "delete_input"),
    Pair("1.INPUT/People/서동현_한성 8기.md",
         "2.OUTPUT/People/Network/서동현(한성 8기).md", "use_input"),
    Pair("1.INPUT/People/송현아_한성 7기, 서울대정외, 외교부인턴, UCLA.md",
         "2.OUTPUT/People/Network/송현아.md", "use_input"),
    Pair("1.INPUT/People/이소현_한성 5기, 화장품, 패션.md",
         "2.OUTPUT/People/Network/이소현(한성 5기) _화장품_패션.md", "delete_input"),
    Pair("1.INPUT/People/이신향_한성 8기.md",
         "2.OUTPUT/People/Network/이신향(한성 8기).md", "delete_input"),
    Pair("1.INPUT/People/최세영_한성 4기, 참치, 개발.md",
         "2.OUTPUT/People/Network/최세영 (한성 4기).md", "use_input"),
    Pair("1.INPUT/People/최현민_한성 9기, 총무, 개발.md",
         "2.OUTPUT/People/Network/최현민 (한성 9기 총무)_개발.md", "delete_input"),
    Pair("1.INPUT/People/황인선_이준석 비서관.md",
         "2.OUTPUT/People/Network/황인선.md", "delete_input"),
]

# After merging, rewrite wikilinks from old stem → canonical stem.
# (Obsidian resolves by stem, so we need to update stems that will no longer exist.)
LINK_REWRITES: dict[str, str] = {
    # INPUT filename stems whose files will be deleted and no longer resolvable
    "권민재_한성 6기, 프린스턴 컴공, 알레프랩": "권민재_프린스턴 컴공_알레프랩",
    "김동희_한성 6기, 서울대 전기정보, 포커": "김동희(한성 6기)_개발_포커",
    "김민재_참치상사, 개발": "김민재_참치상사 개발자",
    "김영진_프로필": "김영진(한성 7기)",
    "김영진_한성 7기": "김영진(한성 7기)",
    "김예지_한성 5기, 서울대컴공-경희대의대, 의료데이터": "김예지(한성 5기)",
    "김욱영_이어드림, 더해커톤 개발, 에이아이당 개발": "김욱영",
    "김유신_한성 6기, 전기정보": "김유신(한성 6기)_전기정보",
    "김지민_한성 3기": "김지민(한성 3기)",
    "김현준_더해커톤, 고3앱스토어1위, 개발자리워드": "김현준_Skrr_머니워크_바이럴",
    "나정현_한성 3기, PD, 영상": "나정현(한성 3기)_PD, 영상",
    "박하나_토스페이먼츠, 매니저": "박하나_토스 페이먼츠 매니저",
    "박혜민_뉴웨이즈 대표, 채용": "박혜민_뉴웨이즈 대표",
    "서동현_한성 8기": "서동현(한성 8기)",
    "송현아_한성 7기, 서울대정외, 외교부인턴, UCLA": "송현아",
    "이소현_한성 5기, 화장품, 패션": "이소현(한성 5기) _화장품_패션",
    "이신향_한성 8기": "이신향(한성 8기)",
    "최세영_한성 4기, 참치, 개발": "최세영 (한성 4기)",
    "최현민_한성 9기, 총무, 개발": "최현민 (한성 9기 총무)_개발",
    "황인선_이준석 비서관": "황인선",
}


def make_backup(pairs: list[Pair]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"vault-phase2b-{ts}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        seen: set[str] = set()
        for p in pairs:
            for rel in (p.input_rel, p.output_rel):
                if rel in seen:
                    continue
                seen.add(rel)
                src = VAULT_ROOT / rel
                if src.exists():
                    tar.add(src, arcname=rel)
    return out


def build_link_patterns(rewrites: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    pats: list[tuple[re.Pattern[str], str]] = []
    # Sort by length desc so longer stems match first (avoid partial overlaps)
    for old in sorted(rewrites.keys(), key=len, reverse=True):
        new = rewrites[old]
        pat = re.compile(r"\[\[" + re.escape(old) + r"(?=[\]\|#])")
        pats.append((pat, f"[[{new}"))
    return pats


def rewrite_wikilinks(apply: bool) -> tuple[int, int]:
    patterns = build_link_patterns(LINK_REWRITES)
    files_touched = 0
    total = 0
    for md in VAULT_ROOT.rglob("*.md"):
        if any(part.startswith(".") for part in md.relative_to(VAULT_ROOT).parts):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text = text
        n_in_file = 0
        for pat, repl in patterns:
            new_text, n = pat.subn(repl, new_text)
            n_in_file += n
        if n_in_file == 0:
            continue
        files_touched += 1
        total += n_in_file
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

    if not VAULT_ROOT.is_dir():
        print(f"vault not found: {VAULT_ROOT}", file=sys.stderr)
        return 2

    # Validate sources exist
    missing: list[str] = []
    for p in PAIRS:
        if not (VAULT_ROOT / p.input_rel).exists():
            missing.append(p.input_rel)
        if not (VAULT_ROOT / p.output_rel).exists():
            missing.append(p.output_rel)
    if missing:
        print("[MISSING SOURCES]")
        for m in missing:
            print(f"   ! {m}")
        print()

    use_input = [p for p in PAIRS if p.action == "use_input"]
    delete_input = [p for p in PAIRS if p.action == "delete_input"]

    print("=" * 72)
    print(f"VAULT CLEANUP — PHASE 2b (INPUT↔OUTPUT People merges)   ({'APPLY' if args.apply else 'DRY-RUN'})")
    print("=" * 72)
    print(f"Vault: {VAULT_ROOT}")
    print()
    print(f"use_input   (overwrite OUTPUT with INPUT body): {len(use_input)}")
    print(f"delete_input (INPUT is stub/duplicate):          {len(delete_input)}")
    print(f"link rewrite rules: {len(LINK_REWRITES)}")
    print()

    print("[USE_INPUT]")
    for p in use_input:
        print(f"   → {Path(p.input_rel).name}")
        print(f"     ==> {p.output_rel}")
    print()
    print("[DELETE_INPUT]")
    for p in delete_input:
        print(f"   × {p.input_rel}")
    print()

    if not args.apply:
        files_touched, total = rewrite_wikilinks(apply=False)
        print(f"Wikilink dry-run: would touch {files_touched} files, {total} replacements")
        print()
        print("(dry-run) no files modified. Re-run with --apply.")
        return 0

    print("Creating backup archive …")
    backup = make_backup(PAIRS)
    print(f"  backup saved: {backup}")
    print()

    overwrote = 0
    deleted = 0
    errors: list[str] = []

    # Step 1: execute use_input (overwrite OUTPUT with INPUT body, delete INPUT)
    for p in use_input:
        src = VAULT_ROOT / p.input_rel
        dest = VAULT_ROOT / p.output_rel
        try:
            content = src.read_text(encoding="utf-8")
            dest.write_text(content, encoding="utf-8")
            src.unlink()
            overwrote += 1
        except OSError as exc:
            errors.append(f"use_input {p.input_rel}: {exc}")

    # Step 2: execute delete_input (just remove INPUT)
    for p in delete_input:
        src = VAULT_ROOT / p.input_rel
        try:
            if src.exists():
                src.unlink()
                deleted += 1
        except OSError as exc:
            errors.append(f"delete_input {p.input_rel}: {exc}")

    print(f"Overwrote {overwrote}/{len(use_input)} OUTPUT files from INPUT.")
    print(f"Deleted {deleted}/{len(delete_input)} INPUT stubs.")
    print()

    print("Rewriting wikilinks across vault …")
    files_touched, total = rewrite_wikilinks(apply=True)
    print(f"  touched {files_touched} files, {total} replacements")

    if errors:
        print()
        print(f"[ERRORS] {len(errors)}")
        for e in errors[:20]:
            print(f"   ! {e}")

    print()
    print("Phase 2b complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
