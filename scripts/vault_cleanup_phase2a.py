"""Phase 2a vault cleanup — strip emoji prefix from remaining People files.

After Phase 1 deleted 75 emoji files that had counterparts in output
People folders, ~295 emoji-prefixed files remain in `1.INPUT/People/`.
Phase 2a strips the emoji from each filename.

Collision handling:
  - If no file with the stripped name exists anywhere → simple rename.
  - If a same-folder non-emoji twin exists (1.INPUT/People/X.md) →
      * byte-identical → delete the emoji version
      * divergent → keep the LARGER file, delete the smaller one
        (user-approved default: "metadata-richer wins")
  - If cross-folder counterpart exists (2.OUTPUT/People/*)   →
      should never happen because Phase 1 already handled it.

After all renames/deletes, wikilinks are rewritten:
  [[👤X]] → [[X]]   and   [[🙍‍♂️X]] → [[X]]
(uses the same safe regex approach as Phase 1)

Usage:
  python scripts/vault_cleanup_phase2a.py            # dry-run
  python scripts/vault_cleanup_phase2a.py --apply    # apply for real
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
PEOPLE_DIR = VAULT_ROOT / "1.INPUT" / "People"
BACKUP_DIR = Path.home() / ".onlime" / "backups"

EMOJI_PREFIXES = ["👤", "🙍‍♂️", "🙍"]


def strip_emoji(name: str) -> str:
    for e in EMOJI_PREFIXES:
        if name.startswith(e):
            return name[len(e):].lstrip()
    return name


def has_emoji_prefix(name: str) -> bool:
    return any(name.startswith(e) for e in EMOJI_PREFIXES)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Plan:
    renames: list[tuple[Path, Path]] = field(default_factory=list)  # (emoji_file, target)
    deletes: list[tuple[Path, str]] = field(default_factory=list)  # (file_to_delete, reason)
    link_rewrites: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def build_plan() -> Plan:
    plan = Plan()
    if not PEOPLE_DIR.is_dir():
        plan.errors.append(f"missing: {PEOPLE_DIR}")
        return plan

    emoji_files = sorted(p for p in PEOPLE_DIR.glob("*.md") if has_emoji_prefix(p.stem))

    for p in emoji_files:
        canonical_stem = strip_emoji(p.stem)
        if not canonical_stem:
            plan.errors.append(f"empty canonical stem: {p.name}")
            continue

        target = PEOPLE_DIR / f"{canonical_stem}.md"
        plan.link_rewrites[p.stem] = canonical_stem

        if not target.exists():
            plan.renames.append((p, target))
            continue

        # Collision with non-emoji twin in same folder
        try:
            same = _sha256(p) == _sha256(target)
        except OSError as exc:
            plan.errors.append(f"hash failed: {p.name} ({exc})")
            continue

        if same:
            plan.deletes.append((p, "byte-identical twin"))
            continue

        # Divergent: keep larger file
        p_size = p.stat().st_size
        t_size = target.stat().st_size
        if p_size > t_size:
            # emoji version is richer — delete twin, then rename
            plan.deletes.append((target, f"smaller twin ({t_size}B) of emoji version ({p_size}B)"))
            plan.renames.append((p, target))
        else:
            # twin is richer or equal — delete emoji version
            plan.deletes.append((p, f"smaller emoji version ({p_size}B) vs twin ({t_size}B)"))

    return plan


def build_link_rewrite_patterns(rewrites: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    pats: list[tuple[re.Pattern[str], str]] = []
    for old, new in rewrites.items():
        pat = re.compile(r"\[\[" + re.escape(old) + r"(?=[\]\|#])")
        pats.append((pat, f"[[{new}"))
    return pats


def rewrite_wikilinks(apply: bool, plan: Plan) -> tuple[int, int]:
    if not plan.link_rewrites:
        return (0, 0)
    patterns = build_link_rewrite_patterns(plan.link_rewrites)
    files_touched = 0
    total = 0
    for md in VAULT_ROOT.rglob("*.md"):
        if any(part.startswith(".") for part in md.relative_to(VAULT_ROOT).parts):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            plan.errors.append(f"read: {md} ({exc})")
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
                plan.errors.append(f"write: {md} ({exc})")
    return (files_touched, total)


def make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"vault-phase2a-{ts}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(PEOPLE_DIR, arcname=str(PEOPLE_DIR.relative_to(VAULT_ROOT)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit-preview", type=int, default=10)
    args = parser.parse_args()

    plan = build_plan()

    print("=" * 72)
    print(f"VAULT CLEANUP — PHASE 2a (emoji strip)   ({'APPLY' if args.apply else 'DRY-RUN'})")
    print("=" * 72)
    print(f"Vault: {VAULT_ROOT}")
    print()
    print(f"Renames:  {len(plan.renames)}")
    print(f"Deletes:  {len(plan.deletes)}")
    print(f"Rewrite rules: {len(plan.link_rewrites)}")
    print()

    print(f"[RENAMES]  (preview {args.limit_preview})")
    for src, dst in plan.renames[: args.limit_preview]:
        print(f"   {src.name}  →  {dst.name}")
    if len(plan.renames) > args.limit_preview:
        print(f"   … {len(plan.renames) - args.limit_preview} more")
    print()

    print(f"[DELETES]  (preview {args.limit_preview})")
    for p, reason in plan.deletes[: args.limit_preview]:
        rel = p.relative_to(VAULT_ROOT) if p.is_relative_to(VAULT_ROOT) else p
        print(f"   {rel}  ({reason})")
    if len(plan.deletes) > args.limit_preview:
        print(f"   … {len(plan.deletes) - args.limit_preview} more")
    print()

    if plan.errors:
        print(f"[ERRORS] {len(plan.errors)}")
        for e in plan.errors[:10]:
            print(f"   ! {e}")
        print()

    if not args.apply:
        files_touched, total = rewrite_wikilinks(apply=False, plan=plan)
        print(f"Wikilink dry-run: would touch {files_touched} files, {total} replacements")
        print()
        print("(dry-run) no files modified. Re-run with --apply.")
        return 0

    print("Creating backup archive …")
    backup = make_backup()
    print(f"  backup saved: {backup}")
    print()

    # Delete first (so renames that clobber a smaller twin work)
    deleted = 0
    for p, _ in plan.deletes:
        try:
            p.unlink()
            deleted += 1
        except OSError as exc:
            plan.errors.append(f"unlink: {p} ({exc})")

    renamed = 0
    for src, dst in plan.renames:
        try:
            src.rename(dst)
            renamed += 1
        except OSError as exc:
            plan.errors.append(f"rename {src} → {dst}: {exc}")

    print(f"Deleted {deleted}/{len(plan.deletes)}  |  Renamed {renamed}/{len(plan.renames)}")

    print("Rewriting wikilinks across vault …")
    files_touched, total = rewrite_wikilinks(apply=True, plan=plan)
    print(f"  touched {files_touched} files, {total} replacements")

    if plan.errors:
        print()
        print(f"[ERRORS] {len(plan.errors)}")
        for e in plan.errors[:20]:
            print(f"   ! {e}")

    print()
    print("Phase 2a complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
