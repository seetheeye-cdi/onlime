"""Phase 3 vault cleanup — merge Think/Projects/* → Projects/*.

For each project folder in `2.OUTPUT/Think/Projects/` that has a twin in
`2.OUTPUT/Projects/`, compare files and consolidate:

  - byte-identical file → delete the Think/Projects copy
  - Think-only file     → move to Projects
  - divergent file      → SKIP and report (manual merge needed)

After all merges, empty Think/Projects subfolders are deleted.
Also deletes `2.OUTPUT/Think/Explore/한성/` if empty.

Usage:
  python scripts/vault_cleanup_phase3.py            # dry-run
  python scripts/vault_cleanup_phase3.py --apply    # apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
import sys
import tarfile
from pathlib import Path

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
THINK_PROJECTS = VAULT_ROOT / "2.OUTPUT" / "Think" / "Projects"
PROJECTS = VAULT_ROOT / "2.OUTPUT" / "Projects"
THINK_EXPLORE_HANSUNG = VAULT_ROOT / "2.OUTPUT" / "Think" / "Explore" / "한성"

# Project subfolders we'll merge
PROJECT_NAMES = ["참치상사", "한성", "더해커톤"]

BACKUP_DIR = Path.home() / ".onlime" / "backups"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(folder: Path) -> dict[str, Path]:
    if not folder.is_dir():
        return {}
    return {p.name: p for p in folder.rglob("*") if p.is_file()}


def make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"vault-phase3-{ts}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        if THINK_PROJECTS.is_dir():
            tar.add(THINK_PROJECTS, arcname=str(THINK_PROJECTS.relative_to(VAULT_ROOT)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not THINK_PROJECTS.is_dir():
        print(f"missing: {THINK_PROJECTS}", file=sys.stderr)
        return 2

    deletes: list[Path] = []       # Think/Projects copies that are identical
    moves: list[tuple[Path, Path]] = []  # unique files (src, dest)
    divergent: list[tuple[Path, Path]] = []  # same name, different content
    errors: list[str] = []

    for name in PROJECT_NAMES:
        think_dir = THINK_PROJECTS / name
        proj_dir = PROJECTS / name
        if not think_dir.is_dir():
            continue
        if not proj_dir.is_dir():
            # Destination doesn't exist — treat every Think file as unique move
            for tf in think_dir.rglob("*"):
                if tf.is_file():
                    rel = tf.relative_to(think_dir)
                    moves.append((tf, proj_dir / rel))
            continue

        proj_by_name = collect_files(proj_dir)

        for tf in think_dir.rglob("*"):
            if not tf.is_file():
                continue
            pf = proj_by_name.get(tf.name)
            if pf is None:
                # Unique Think file — move to Projects
                rel = tf.relative_to(think_dir)
                moves.append((tf, proj_dir / rel))
                continue
            try:
                same = _sha256(tf) == _sha256(pf)
            except OSError as exc:
                errors.append(f"hash: {tf} ({exc})")
                continue
            if same:
                deletes.append(tf)
            else:
                divergent.append((tf, pf))

    # Print plan
    print("=" * 72)
    print(f"VAULT CLEANUP — PHASE 3 (Think/Projects → Projects)   ({'APPLY' if args.apply else 'DRY-RUN'})")
    print("=" * 72)
    print(f"Vault: {VAULT_ROOT}")
    print()
    print(f"Delete (identical):  {len(deletes)}")
    print(f"Move   (unique):     {len(moves)}")
    print(f"Skip   (divergent):  {len(divergent)}")
    print()

    for name in PROJECT_NAMES:
        d_count = sum(1 for p in deletes if name in str(p))
        m_count = sum(1 for s, _ in moves if name in str(s))
        x_count = sum(1 for s, _ in divergent if name in str(s))
        print(f"  {name}:  delete={d_count}  move={m_count}  skip={x_count}")
    print()

    if moves:
        print(f"[MOVES] (preview 10)")
        for s, d in moves[:10]:
            print(f"   + {s.relative_to(VAULT_ROOT)}")
            print(f"       → {d.relative_to(VAULT_ROOT)}")
        if len(moves) > 10:
            print(f"   … {len(moves) - 10} more")
        print()

    if divergent:
        print(f"[DIVERGENT] (preview 10)")
        for s, p in divergent[:10]:
            print(f"   ✗ {s.relative_to(VAULT_ROOT)}")
            print(f"     vs {p.relative_to(VAULT_ROOT)}")
        if len(divergent) > 10:
            print(f"   … {len(divergent) - 10} more")
        print()

    if errors:
        print(f"[ERRORS] {len(errors)}")
        for e in errors[:10]:
            print(f"   ! {e}")
        print()

    if not args.apply:
        print("(dry-run) no files modified. Re-run with --apply.")
        return 0

    print("Creating backup archive …")
    backup = make_backup()
    print(f"  backup saved: {backup}")
    print()

    deleted = 0
    for p in deletes:
        try:
            p.unlink()
            deleted += 1
        except OSError as exc:
            errors.append(f"unlink: {p} ({exc})")

    moved = 0
    for s, d in moves:
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            if d.exists():
                # Shouldn't happen but guard anyway
                stem, ext = d.stem, d.suffix
                i = 2
                while True:
                    alt = d.with_name(f"{stem} ({i}){ext}")
                    if not alt.exists():
                        d = alt
                        break
                    i += 1
            shutil.move(str(s), str(d))
            moved += 1
        except OSError as exc:
            errors.append(f"move: {s} → {d} ({exc})")

    print(f"Deleted {deleted}/{len(deletes)}  |  Moved {moved}/{len(moves)}")
    if divergent:
        print(f"Skipped {len(divergent)} divergent conflicts.")

    # Remove now-empty Think/Projects subfolders
    removed_dirs = 0
    for name in PROJECT_NAMES:
        d = THINK_PROJECTS / name
        if d.is_dir():
            # Remove empty subfolders bottom-up
            for sub in sorted(d.rglob("*"), key=lambda p: -len(str(p))):
                if sub.is_dir():
                    try:
                        sub.rmdir()
                    except OSError:
                        pass
            try:
                if not any(d.iterdir()):
                    d.rmdir()
                    removed_dirs += 1
            except OSError as exc:
                errors.append(f"rmdir: {d} ({exc})")
    print(f"Removed {removed_dirs}/{len(PROJECT_NAMES)} Think/Projects subfolders")

    # Also remove empty Think/Explore/한성/ if it exists
    if THINK_EXPLORE_HANSUNG.is_dir():
        try:
            if not any(THINK_EXPLORE_HANSUNG.iterdir()):
                THINK_EXPLORE_HANSUNG.rmdir()
                print(f"Removed empty {THINK_EXPLORE_HANSUNG.relative_to(VAULT_ROOT)}")
        except OSError as exc:
            errors.append(f"rmdir: {THINK_EXPLORE_HANSUNG} ({exc})")

    if errors:
        print()
        print(f"[ERRORS] {len(errors)}")
        for e in errors[:20]:
            print(f"   ! {e}")

    print()
    print("Phase 3 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
