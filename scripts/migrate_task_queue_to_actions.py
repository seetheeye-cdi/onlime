"""One-shot migration from task_queue action_item rows to action_lifecycle table.
Currently a no-op (0 action_item rows verified 2026-04-11), but preserved for
idempotency and future safety.

Usage:
  python scripts/migrate_task_queue_to_actions.py           # dry-run (default)
  python scripts/migrate_task_queue_to_actions.py --apply   # apply for real
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import aiosqlite

DB_PATH = Path.home() / ".onlime" / "onlime.db"

_STATE_MAP: dict[str, str] = {
    "pending": "open",
    "processing": "open",
    "completed": "completed",
    "done": "completed",
    "failed": "blocked",
}


async def _run(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[migrate_task_queue_to_actions] mode={mode} db={DB_PATH}")

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT id, task_type, input_path, status, created_at, result "
            "FROM task_queue WHERE task_type='action_item'"
        )
        rows = await cursor.fetchall()

        found = len(rows)
        migrated = 0
        skipped = 0
        errors = 0

        for row in rows:
            try:
                result_raw = row["result"]
                data: dict = {}
                if result_raw:
                    try:
                        data = json.loads(result_raw)
                    except (json.JSONDecodeError, TypeError):
                        pass

                task_text = data.get("task_text") or data.get("text") or f"(from task_queue id={row['id']})"
                owner = data.get("owner")
                due_at = data.get("due_date") or data.get("due_at")
                source_note_path = data.get("source_note_path") or row["input_path"]
                state = _STATE_MAP.get(row["status"] or "pending", "open")

                if not task_text.strip():
                    skipped += 1
                    print(f"  SKIP  task_queue.id={row['id']} — empty task_text")
                    continue

                print(
                    f"  {'WOULD INSERT' if not apply else 'INSERT'} "
                    f"task_queue.id={row['id']} state={state} task_text={task_text!r:.60}"
                )

                if apply:
                    await db.execute(
                        """INSERT INTO action_lifecycle
                           (task_text, state, owner, source_note_path, due_at, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            task_text,
                            state,
                            owner,
                            source_note_path,
                            due_at,
                            row["created_at"] or datetime.now().isoformat(),
                            datetime.now().isoformat(),
                        ),
                    )
                migrated += 1

            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"  ERROR task_queue.id={row['id']}: {exc}")

        if apply and migrated:
            await db.commit()

    print(
        f"[migrate_task_queue_to_actions] done — "
        f"found={found} migrated={migrated} skipped={skipped} errors={errors}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate task_queue action_items → action_lifecycle")
    parser.add_argument("--apply", action="store_true", help="Actually write rows (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    main()
