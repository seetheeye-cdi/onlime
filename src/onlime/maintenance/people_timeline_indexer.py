"""PeopleTimelineIndexer — realtime + one-time backfill into people_timeline."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask

if TYPE_CHECKING:
    from onlime.processors.people_crm import PeopleCRM
    from onlime.state.store import StateStore

logger = structlog.get_logger()

BACKFILL_MARKER = "people_timeline_backfill"  # connector_state key

# Vault People directories to scan during backfill
_PEOPLE_DIRS = [
    "1.INPUT/People",
    "2.OUTPUT/People/Active",
    "2.OUTPUT/People/Network",
    "2.OUTPUT/People/Reference",
]


class PeopleTimelineIndexerTask(BackgroundTask):
    name = "people_timeline_indexer"

    def __init__(
        self,
        store: "StateStore",
        crm: "PeopleCRM",
        vault_root: Path,
        interval_seconds: int = 1800,
    ) -> None:
        super().__init__(interval_seconds)
        self._store = store
        self._crm = crm
        self._vault_root = vault_root

    async def run_once(self) -> None:
        """Called by BackgroundTask scheduler. Gated on feature flag."""
        settings = get_settings()
        flags = getattr(settings, "feature_flags", None)
        if not (flags and getattr(flags, "people_crm", False)):
            return

        marker = await self._store.get_connector_state(BACKFILL_MARKER)
        if not marker or not marker.get("done"):
            logger.info("people_timeline.backfill_start")
            count = await self.run_backfill()
            await self._store.save_connector_state(
                BACKFILL_MARKER,
                {"done": True, "rows": count, "finished_at": datetime.now().isoformat()},
            )
            logger.info("people_timeline.backfill_done", rows=count)
        else:
            logger.debug("people_timeline.backfill_skip", marker=marker)

        # Refresh People auto-sections for recently modified files
        try:
            from onlime.outputs.people_profile import refresh_people_profiles
            cutoff = datetime.now() - timedelta(hours=2)
            await refresh_people_profiles(self._crm, self._vault_root, modified_since=cutoff, limit=50)
        except Exception:
            logger.exception("people_timeline.refresh_profiles_failed")

    async def run_backfill(self) -> int:
        """One-time: scan existing events + vault People files, populate timeline.
        Returns rows inserted."""
        count = 0

        # Part 1: existing events table
        async for row in self._store.iter_events_for_backfill():
            payload_dict: dict = {}
            if row.get("payload"):
                try:
                    payload_dict = json.loads(row["payload"])
                except (json.JSONDecodeError, TypeError):
                    pass
            people_list: list[str] = payload_dict.get("people", [])
            if not people_list:
                continue
            inserted = await self._crm.record_interactions_for_event(
                event_id=row["id"],
                people=people_list,
                source_type=row["source_type"],
                timestamp=row["created_at"],
            )
            count += inserted

        # Part 2: vault People files
        vault = Path(self._vault_root).expanduser()
        for rel_dir in _PEOPLE_DIRS:
            dir_path = vault / rel_dir
            if not dir_path.is_dir():
                continue
            for md_file in dir_path.rglob("*.md"):
                try:
                    stem = md_file.stem
                    first_seen = datetime.fromtimestamp(md_file.stat().st_ctime).isoformat()
                    display_name = stem.split("_", 1)[0]
                    await self._crm.upsert_person(
                        canonical_name=stem,
                        display_name=display_name,
                    )
                    await self._crm.record_vault_scan(
                        person_name=stem,
                        source_path=str(md_file),
                        timestamp=first_seen,
                    )
                    count += 1
                except Exception:
                    logger.warning("people_timeline.backfill_file_error", path=str(md_file))

        return count
