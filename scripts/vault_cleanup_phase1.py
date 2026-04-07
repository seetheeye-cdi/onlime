"""Phase 1 vault cleanup — safe duplicate deletion.

Scope (user-approved defaults, 2026-04-06):
  1. Delete stray 0-byte `윤준호.md` at vault root.
  2. Delete emoji-prefixed People files (`👤…`, `🙍‍♂️…`) in `1.INPUT/People/`
     IF a non-emoji counterpart already exists in
     `2.OUTPUT/People/{Network,Reference,Active}/`.
  3. Delete byte-identical `2.OUTPUT/Explore/` files that duplicate files
     in `2.OUTPUT/Think/Explore/` (keep Think/Explore version per review).
  4. Rewrite all wikilinks across the vault so `[[👤name]]` / `[[🙍‍♂️name]]`
     become `[[name]]`, keeping backlinks alive.

Defaults to dry-run. Pass `--apply` to actually modify files.
A tar.gz backup of affected folders is created before apply.

Usage:
  python scripts/vault_cleanup_phase1.py            # dry-run
  python scripts/vault_cleanup_phase1.py --apply    # apply for real
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import shutil
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")

# Emoji prefixes we're removing. Keep the exact sequences including ZWJ.
EMOJI_PREFIXES = ["👤", "🙍‍♂️", "🙍"]

PEOPLE_INPUT_DIR = VAULT_ROOT / "1.INPUT" / "People"
PEOPLE_OUTPUT_DIRS = [
    VAULT_ROOT / "2.OUTPUT" / "People" / "Network",
    VAULT_ROOT / "2.OUTPUT" / "People" / "Reference",
    VAULT_ROOT / "2.OUTPUT" / "People" / "Active",
]

EXPLORE_A = VAULT_ROOT / "2.OUTPUT" / "Explore"
EXPLORE_B = VAULT_ROOT / "2.OUTPUT" / "Think" / "Explore"

STRAY_ROOT_FILE = VAULT_ROOT / "윤준호.md"

BACKUP_DIR = Path.home() / ".onlime" / "backups"


@dataclass
class Action:
    kind: str  # "delete", "rewrite"
    path: Path
    reason: str
    detail: str = ""


@dataclass
class Plan:
    deletes: list[Action] = field(default_factory=list)
    link_rewrites: dict[str, str] = field(default_factory=dict)  # old_name → new_name (no [[]], no .md)
    errors: list[str] = field(default_factory=list)


def strip_emoji(name: str) -> str:
    """Remove leading emoji prefix from a filename stem or wikilink target."""
    for e in EMOJI_PREFIXES:
        if name.startswith(e):
            return name[len(e):].lstrip()
    return name


def has_emoji_prefix(name: str) -> bool:
    return any(name.startswith(e) for e in EMOJI_PREFIXES)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_output_index() -> dict[str, Path]:
    """Map stem → path for every People output file (Network/Reference/Active)."""
    idx: dict[str, Path] = {}
    for d in PEOPLE_OUTPUT_DIRS:
        if not d.is_dir():
            continue
        for p in d.glob("*.md"):
            idx[p.stem] = p
    return idx


# ----- plan builders -----


def plan_stray_root(plan: Plan) -> None:
    if STRAY_ROOT_FILE.exists() and STRAY_ROOT_FILE.stat().st_size == 0:
        plan.deletes.append(
            Action(
                kind="delete",
                path=STRAY_ROOT_FILE,
                reason="stray 0-byte root file",
            )
        )


def plan_people_emoji_dupes(plan: Plan) -> None:
    if not PEOPLE_INPUT_DIR.is_dir():
        plan.errors.append(f"missing dir: {PEOPLE_INPUT_DIR}")
        return
    output_idx = build_output_index()

    for p in sorted(PEOPLE_INPUT_DIR.glob("*.md")):
        if not has_emoji_prefix(p.stem):
            continue
        canonical_stem = strip_emoji(p.stem)
        if not canonical_stem:
            continue

        target = output_idx.get(canonical_stem)
        if target is None:
            # No counterpart in output — skip (Phase 2 will handle via rename).
            continue

        plan.deletes.append(
            Action(
                kind="delete",
                path=p,
                reason="emoji-prefixed duplicate of output People entry",
                detail=f"→ {target.relative_to(VAULT_ROOT)}",
            )
        )
        # Record wikilink rewrite: old stem → canonical stem
        plan.link_rewrites[p.stem] = canonical_stem


def plan_explore_mirrors(plan: Plan) -> None:
    """Delete 2.OUTPUT/Explore/*.md that are byte-identical to 2.OUTPUT/Think/Explore/*.md."""
    if not EXPLORE_A.is_dir() or not EXPLORE_B.is_dir():
        return

    think_explore_files = {p.name: p for p in EXPLORE_B.glob("*.md")}
    for a in sorted(EXPLORE_A.glob("*.md")):
        b = think_explore_files.get(a.name)
        if b is None:
            continue
        try:
            if sha256_of(a) != sha256_of(b):
                continue
        except OSError as exc:
            plan.errors.append(f"hash failed: {a} ({exc})")
            continue
        plan.deletes.append(
            Action(
                kind="delete",
                path=a,
                reason="byte-identical mirror of Think/Explore",
                detail=f"keep {b.relative_to(VAULT_ROOT)}",
            )
        )


# ----- wikilink rewriter -----


def build_link_rewrite_patterns(rewrites: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """Build regex patterns that match `[[old_stem]]` or `[[old_stem|display]]` or `[[old_stem#heading]]`."""
    patterns: list[tuple[re.Pattern[str], str]] = []
    for old, new in rewrites.items():
        # Match [[<old>]] OR [[<old>|...]] OR [[<old>#...]]
        # Use re.escape for emoji+Korean safety.
        pat = re.compile(
            r"\[\[" + re.escape(old) + r"(?=[\]\|#])"
        )
        patterns.append((pat, f"[[{new}"))
    return patterns


def rewrite_wikilinks(apply: bool, plan: Plan) -> tuple[int, int]:
    """Walk all vault .md files and rewrite links per plan.link_rewrites.

    Returns (files_touched, total_replacements).
    """
    if not plan.link_rewrites:
        return (0, 0)

    patterns = build_link_rewrite_patterns(plan.link_rewrites)

    files_touched = 0
    total_replacements = 0

    delete_set = {a.path for a in plan.deletes if a.kind == "delete"}

    for md in VAULT_ROOT.rglob("*.md"):
        # Skip hidden dirs like .trash, .obsidian etc.
        if any(part.startswith(".") for part in md.relative_to(VAULT_ROOT).parts):
            continue
        # Skip files queued for deletion (pointless to rewrite them).
        if md in delete_set:
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            plan.errors.append(f"read failed: {md} ({exc})")
            continue

        new_text = text
        file_replacements = 0
        for pat, repl in patterns:
            new_text, n = pat.subn(repl, new_text)
            file_replacements += n

        if file_replacements == 0:
            continue
        files_touched += 1
        total_replacements += file_replacements

        if apply:
            try:
                md.write_text(new_text, encoding="utf-8")
            except OSError as exc:
                plan.errors.append(f"write failed: {md} ({exc})")

    return (files_touched, total_replacements)


# ----- backup -----


def make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"vault-phase1-{ts}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        for d in [PEOPLE_INPUT_DIR, EXPLORE_A]:
            if d.is_dir():
                tar.add(d, arcname=str(d.relative_to(VAULT_ROOT)))
        if STRAY_ROOT_FILE.exists():
            tar.add(STRAY_ROOT_FILE, arcname=STRAY_ROOT_FILE.name)
    return out


# ----- main -----


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually perform deletions and rewrites")
    parser.add_argument("--limit-preview", type=int, default=15, help="Max actions to preview per category")
    args = parser.parse_args()

    if not VAULT_ROOT.is_dir():
        print(f"Vault not found: {VAULT_ROOT}", file=sys.stderr)
        return 2

    plan = Plan()
    plan_stray_root(plan)
    plan_people_emoji_dupes(plan)
    plan_explore_mirrors(plan)

    # ---- print plan ----
    print("=" * 72)
    print(f"VAULT CLEANUP — PHASE 1   ({'APPLY' if args.apply else 'DRY-RUN'})")
    print("=" * 72)
    print(f"Vault:  {VAULT_ROOT}")
    print()

    by_reason: dict[str, list[Action]] = {}
    for a in plan.deletes:
        by_reason.setdefault(a.reason, []).append(a)

    for reason, actions in by_reason.items():
        print(f"[DELETE] {reason}: {len(actions)} file(s)")
        for a in actions[: args.limit_preview]:
            rel = a.path.relative_to(VAULT_ROOT) if a.path.is_relative_to(VAULT_ROOT) else a.path
            extra = f"  ({a.detail})" if a.detail else ""
            print(f"   - {rel}{extra}")
        if len(actions) > args.limit_preview:
            print(f"   … {len(actions) - args.limit_preview} more")
        print()

    print(f"[WIKILINK REWRITES] {len(plan.link_rewrites)} rewrite rules")
    shown = 0
    for old, new in list(plan.link_rewrites.items())[: args.limit_preview]:
        print(f"   [[{old}]] → [[{new}]]")
        shown += 1
    if len(plan.link_rewrites) > shown:
        print(f"   … {len(plan.link_rewrites) - shown} more")
    print()

    if plan.errors:
        print(f"[ERRORS] {len(plan.errors)}")
        for e in plan.errors[:10]:
            print(f"   ! {e}")
        print()

    # ---- apply or stop ----
    if not args.apply:
        # Still measure wikilink impact in dry-run (read-only).
        files_touched, total_reps = rewrite_wikilinks(apply=False, plan=plan)
        print(f"Wikilink dry-run: would touch {files_touched} files, {total_reps} replacements")
        print()
        print("(dry-run) no files were modified. Re-run with --apply to execute.")
        return 0

    # Backup
    print("Creating backup archive …")
    backup = make_backup()
    print(f"  backup saved: {backup}")
    print()

    # Delete files
    deleted = 0
    for a in plan.deletes:
        try:
            a.path.unlink()
            deleted += 1
        except OSError as exc:
            plan.errors.append(f"unlink failed: {a.path} ({exc})")
    print(f"Deleted {deleted}/{len(plan.deletes)} files.")

    # Rewrite wikilinks
    print("Rewriting wikilinks across vault …")
    files_touched, total_reps = rewrite_wikilinks(apply=True, plan=plan)
    print(f"  touched {files_touched} files, {total_reps} replacements")

    if plan.errors:
        print()
        print(f"[ERRORS] {len(plan.errors)}")
        for e in plan.errors[:20]:
            print(f"   ! {e}")

    print()
    print("Phase 1 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
