"""People CRM — canonical record + timeline aggregates built on StateStore."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, TYPE_CHECKING

import structlog

from onlime.config import get_settings

if TYPE_CHECKING:
    from onlime.state.store import StateStore
    from onlime.processors.people_resolver import PeopleResolver
    from onlime.processors.name_resolver import VaultNameIndex

logger = structlog.get_logger()


@dataclass
class PersonRecord:
    canonical_name: str              # = people.id
    display_name: str                # = people.name (usually same as canonical minus suffix)
    wikilink: str                    # [[...]] form
    aliases: list[str] = field(default_factory=list)
    kakao_name: str | None = None
    telegram_username: str | None = None
    first_seen: str | None = None            # ISO 8601
    last_seen: str | None = None             # ISO 8601
    interaction_count: int = 0
    sources: dict[str, int] = field(default_factory=dict)    # {'telegram': 5, 'kakao': 12}
    recent_relations: list[str] = field(default_factory=list)  # most recent N relation_kinds
    vault_profile_path: str | None = None


class PeopleCRM:
    """Read/write layer over people + people_timeline tables."""

    def __init__(
        self,
        store: "StateStore",
        resolver: "PeopleResolver",
        name_index: "VaultNameIndex",
    ) -> None:
        self._store = store
        self._resolver = resolver
        self._name_index = name_index

    async def upsert_person(
        self,
        *,
        canonical_name: str,
        display_name: str | None = None,
        wikilink: str | None = None,
        aliases: list[str] | None = None,
        kakao_name: str | None = None,
        telegram_username: str | None = None,
    ) -> None:
        """Insert or update a row in the existing `people` table."""
        if display_name is None:
            display_name = canonical_name.split("_", 1)[0]
        if wikilink is None:
            wikilink = f"[[{canonical_name}]]"
        now = datetime.now().isoformat()
        await self._store.db.execute(
            """INSERT OR REPLACE INTO people
               (id, name, wikilink, aliases, kakao_name, telegram_username, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                canonical_name,
                display_name,
                wikilink,
                json.dumps(aliases or [], ensure_ascii=False),
                kakao_name,
                telegram_username,
                now,
            ),
        )
        await self._store.db.commit()

    async def record_interactions_for_event(
        self,
        *,
        event_id: str,
        people: list[str],
        source_type: str,
        timestamp: str,
        context_excerpt: str | None = None,
    ) -> int:
        """For each person in `people`, resolve canonical name then insert a timeline row.
        Also upserts the person into the `people` table if not already there.
        Returns count of rows inserted.
        Double-gates on feature flag."""
        flags = getattr(get_settings(), "feature_flags", None)
        if not (flags and getattr(flags, "people_crm", False)):
            return 0

        count = 0
        for raw_name in people:
            canonical = self._resolver.resolve(raw_name)
            if canonical is None:
                canonical = self._name_index.match(raw_name)
            if canonical is None:
                logger.warning("people_crm.unresolved_name", raw_name=raw_name, event_id=event_id)
                canonical = raw_name

            await self.upsert_person(canonical_name=canonical)
            await self._store.insert_timeline_event(
                person_name=canonical,
                event_id=event_id,
                source_path=None,
                timestamp=timestamp,
                source_type=source_type,
                relation_kind="mention",
                context_excerpt=context_excerpt,
            )
            count += 1

        return count

    async def record_vault_scan(
        self,
        *,
        person_name: str,
        source_path: str,
        timestamp: str,
        relation_kind: str = "vault_file",
    ) -> None:
        """Insert a single vault_scan source timeline row."""
        await self._store.insert_timeline_event(
            person_name=person_name,
            event_id=None,
            source_path=source_path,
            timestamp=timestamp,
            source_type="vault_scan",
            relation_kind=relation_kind,
        )

    async def get_person_profile(self, name: str) -> PersonRecord | None:
        """Resolve `name` through PeopleResolver → canonical stem, then build PersonRecord."""
        canonical = self._resolver.resolve(name)
        if canonical is None:
            canonical = self._name_index.match(name)
        if canonical is None:
            canonical = name

        # Query people table
        cursor = await self._store.db.execute(
            "SELECT id, name, wikilink, aliases, kakao_name, telegram_username FROM people WHERE id = ?",
            (canonical,),
        )
        row = await cursor.fetchone()

        # Get timeline aggregates
        stats = await self._store.get_person_stats(canonical)
        if row is None and stats["interaction_count"] == 0:
            return None

        if row:
            aliases_raw = row["aliases"] or "[]"
            try:
                aliases = json.loads(aliases_raw)
            except (json.JSONDecodeError, TypeError):
                aliases = []
            display_name = row["name"] or canonical.split("_", 1)[0]
            wikilink = row["wikilink"] or f"[[{canonical}]]"
            kakao_name = row["kakao_name"]
            telegram_username = row["telegram_username"]
        else:
            aliases = []
            display_name = canonical.split("_", 1)[0]
            wikilink = f"[[{canonical}]]"
            kakao_name = None
            telegram_username = None

        # Recent timeline entries for relation_kinds
        recent_rows = await self._store.get_person_timeline(canonical, limit=10)
        recent_relations = [r["relation_kind"] for r in recent_rows if r.get("relation_kind")]

        # Try to locate vault profile path via name_index
        vault_profile_path: str | None = None
        entity = self._name_index._by_stem.get(canonical)
        if entity:
            vault_profile_path = str(entity.path)

        return PersonRecord(
            canonical_name=canonical,
            display_name=display_name,
            wikilink=wikilink,
            aliases=aliases,
            kakao_name=kakao_name,
            telegram_username=telegram_username,
            first_seen=stats["first_seen"],
            last_seen=stats["last_seen"],
            interaction_count=stats["interaction_count"],
            sources=stats["sources"],
            recent_relations=recent_relations,
            vault_profile_path=vault_profile_path,
        )

    async def get_recent_people(self, *, days: int = 7, limit: int = 20) -> list[PersonRecord]:
        """Return PersonRecords touched in the last N days, ordered by last_seen DESC."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = await self._store.db.execute(
            """SELECT person_name, MAX(timestamp) AS last_seen
               FROM people_timeline
               WHERE timestamp >= ?
               GROUP BY person_name
               ORDER BY last_seen DESC
               LIMIT ?""",
            (since, limit),
        )
        rows = await cursor.fetchall()
        results: list[PersonRecord] = []
        for row in rows:
            profile = await self.get_person_profile(row["person_name"])
            if profile:
                results.append(profile)
        return results

    async def get_pending_actions_for_person(self, canonical_name: str) -> list[dict[str, Any]]:
        """Return open/in_progress/waiting_on_other actions owned by this person."""
        result: list[dict[str, Any]] = []
        for state in ("open", "in_progress", "waiting_on_other"):
            rows = await self._store.get_actions_by_state(state, owner=canonical_name)
            result.extend(rows)
        return result
