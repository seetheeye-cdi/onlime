"""Tests for PeopleCRM — mocked StateStore/PeopleResolver/VaultNameIndex."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onlime.processors.people_crm import PeopleCRM, PersonRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_store():
    store = MagicMock()
    store.db = AsyncMock()
    store.db.execute = AsyncMock()
    store.db.commit = AsyncMock()
    store.insert_timeline_event = AsyncMock(return_value=1)
    store.get_person_stats = AsyncMock(return_value={
        "first_seen": None,
        "last_seen": None,
        "interaction_count": 0,
        "sources": {},
    })
    store.get_person_timeline = AsyncMock(return_value=[])
    store.get_actions_by_state = AsyncMock(return_value=[])
    return store


def _make_mock_resolver(resolved: str | None = "김단영_파트너"):
    resolver = MagicMock()
    resolver.resolve = MagicMock(return_value=resolved)
    return resolver


def _make_mock_name_index(matched: str | None = None):
    index = MagicMock()
    index.match = MagicMock(return_value=matched)
    index._by_stem = {}
    return index


def _make_crm(store=None, resolver=None, name_index=None):
    return PeopleCRM(
        store=store or _make_mock_store(),
        resolver=resolver or _make_mock_resolver(),
        name_index=name_index or _make_mock_name_index(),
    )


# ---------------------------------------------------------------------------
# D4.1 — PersonRecord dataclass defaults
# ---------------------------------------------------------------------------

def test_person_record_dataclass_defaults():
    rec = PersonRecord(canonical_name="홍길동", display_name="홍길동", wikilink="[[홍길동]]")
    assert rec.canonical_name == "홍길동"
    assert rec.aliases == []
    assert rec.kakao_name is None
    assert rec.telegram_username is None
    assert rec.first_seen is None
    assert rec.last_seen is None
    assert rec.interaction_count == 0
    assert rec.sources == {}
    assert rec.recent_relations == []
    assert rec.vault_profile_path is None


# ---------------------------------------------------------------------------
# D4.2 — upsert_person issues correct SQL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_person_inserts_row():
    store = _make_mock_store()

    # Simulate fetchone returning a cursor-like object for execute
    mock_cursor = AsyncMock()
    store.db.execute = AsyncMock(return_value=mock_cursor)
    store.db.commit = AsyncMock()

    crm = _make_crm(store=store)
    await crm.upsert_person(
        canonical_name="김단영_파트너",
        display_name="김단영",
        wikilink="[[김단영_파트너]]",
    )

    store.db.execute.assert_called_once()
    call_args = store.db.execute.call_args
    sql = call_args[0][0]
    assert "INSERT OR REPLACE INTO people" in sql
    params = call_args[0][1]
    assert params[0] == "김단영_파트너"
    assert params[1] == "김단영"
    assert params[2] == "[[김단영_파트너]]"
    store.db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# D4.3 — record_interactions_for_event happy path (3 people)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_interactions_for_event_happy_path():
    store = _make_mock_store()
    mock_cursor = AsyncMock()
    store.db.execute = AsyncMock(return_value=mock_cursor)
    store.db.commit = AsyncMock()
    store.insert_timeline_event = AsyncMock(return_value=1)

    resolver = _make_mock_resolver(resolved="canonical_person")
    name_index = _make_mock_name_index()
    crm = _make_crm(store=store, resolver=resolver, name_index=name_index)

    with patch("onlime.processors.people_crm.get_settings") as mock_settings:
        flags = MagicMock()
        flags.people_crm = True
        mock_settings.return_value.feature_flags = flags

        result = await crm.record_interactions_for_event(
            event_id="evt-001",
            people=["이태양", "김단영", "박도현"],
            source_type="telegram",
            timestamp="2026-04-11T10:00:00",
        )

    assert result == 3
    assert store.insert_timeline_event.call_count == 3
    # Verify each call used the resolved canonical name
    for call in store.insert_timeline_event.call_args_list:
        assert call.kwargs["person_name"] == "canonical_person"
        assert call.kwargs["source_type"] == "telegram"
        assert call.kwargs["event_id"] == "evt-001"


# ---------------------------------------------------------------------------
# D4.4 — unresolved name falls back to raw name + logs warning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_interactions_unresolved_name_fallback():
    store = _make_mock_store()
    mock_cursor = AsyncMock()
    store.db.execute = AsyncMock(return_value=mock_cursor)
    store.db.commit = AsyncMock()
    store.insert_timeline_event = AsyncMock(return_value=1)

    resolver = _make_mock_resolver(resolved=None)
    name_index = _make_mock_name_index(matched=None)
    crm = _make_crm(store=store, resolver=resolver, name_index=name_index)

    with patch("onlime.processors.people_crm.get_settings") as mock_settings:
        flags = MagicMock()
        flags.people_crm = True
        mock_settings.return_value.feature_flags = flags

        with patch("onlime.processors.people_crm.logger") as mock_logger:
            result = await crm.record_interactions_for_event(
                event_id="evt-002",
                people=["미등록인물"],
                source_type="kakao",
                timestamp="2026-04-11T11:00:00",
            )
            mock_logger.warning.assert_called_once()
            warning_call = mock_logger.warning.call_args
            assert "unresolved_name" in warning_call[0][0]

    assert result == 1
    # Timeline row still inserted using raw name as fallback
    store.insert_timeline_event.assert_called_once()
    assert store.insert_timeline_event.call_args.kwargs["person_name"] == "미등록인물"


# ---------------------------------------------------------------------------
# D4.5 — get_person_profile joins people + stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_person_profile_joins_people_and_stats():
    store = _make_mock_store()

    # people table row
    people_row = MagicMock()
    people_row.__getitem__ = lambda self, key: {
        "id": "김단영_파트너",
        "name": "김단영",
        "wikilink": "[[김단영_파트너]]",
        "aliases": '["단영"]',
        "kakao_name": "단영이",
        "telegram_username": "@danyang",
    }[key]

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=people_row)
    store.db.execute = AsyncMock(return_value=mock_cursor)

    store.get_person_stats = AsyncMock(return_value={
        "first_seen": "2026-01-01T00:00:00",
        "last_seen": "2026-04-11T10:00:00",
        "interaction_count": 12,
        "sources": {"telegram": 8, "kakao": 4},
    })
    store.get_person_timeline = AsyncMock(return_value=[
        {"relation_kind": "mention"},
        {"relation_kind": "vault_file"},
    ])

    resolver = _make_mock_resolver(resolved="김단영_파트너")
    name_index = _make_mock_name_index()
    name_index._by_stem = {}
    crm = _make_crm(store=store, resolver=resolver, name_index=name_index)

    profile = await crm.get_person_profile("김단영")

    assert profile is not None
    assert profile.canonical_name == "김단영_파트너"
    assert profile.display_name == "김단영"
    assert profile.wikilink == "[[김단영_파트너]]"
    assert profile.aliases == ["단영"]
    assert profile.kakao_name == "단영이"
    assert profile.telegram_username == "@danyang"
    assert profile.interaction_count == 12
    assert profile.sources == {"telegram": 8, "kakao": 4}
    assert "mention" in profile.recent_relations


# ---------------------------------------------------------------------------
# D4.6 — get_person_profile returns None when not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_person_profile_not_found():
    store = _make_mock_store()

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    store.db.execute = AsyncMock(return_value=mock_cursor)
    store.get_person_stats = AsyncMock(return_value={
        "first_seen": None,
        "last_seen": None,
        "interaction_count": 0,
        "sources": {},
    })
    store.get_person_timeline = AsyncMock(return_value=[])

    resolver = _make_mock_resolver(resolved=None)
    name_index = _make_mock_name_index(matched=None)
    name_index._by_stem = {}
    crm = _make_crm(store=store, resolver=resolver, name_index=name_index)

    profile = await crm.get_person_profile("없는사람")
    assert profile is None


# ---------------------------------------------------------------------------
# D4.7 — get_pending_actions_for_person filters correct states
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_actions_filters_correct_states():
    store = _make_mock_store()
    open_action = {"task_id": 1, "state": "open", "owner": "김단영_파트너", "task_text": "리포트 작성"}
    inprogress_action = {"task_id": 2, "state": "in_progress", "owner": "김단영_파트너", "task_text": "코드 리뷰"}
    waiting_action = {"task_id": 3, "state": "waiting_on_other", "owner": "김단영_파트너", "task_text": "승인 대기"}

    async def _get_actions_by_state(state, *, owner=None, limit=100):
        if state == "open":
            return [open_action]
        if state == "in_progress":
            return [inprogress_action]
        if state == "waiting_on_other":
            return [waiting_action]
        return []

    store.get_actions_by_state = AsyncMock(side_effect=_get_actions_by_state)

    crm = _make_crm(store=store)
    actions = await crm.get_pending_actions_for_person("김단영_파트너")

    assert len(actions) == 3
    states = {a["state"] for a in actions}
    assert states == {"open", "in_progress", "waiting_on_other"}

    # Verify get_actions_by_state was called exactly 3 times with the right states
    calls = store.get_actions_by_state.call_args_list
    called_states = {c[0][0] for c in calls}
    assert called_states == {"open", "in_progress", "waiting_on_other"}
    for c in calls:
        assert c.kwargs.get("owner") == "김단영_파트너"
