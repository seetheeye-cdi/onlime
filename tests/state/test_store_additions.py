"""Tests for new StateStore tables: people_timeline, action_lifecycle, synthesis_cache."""

from __future__ import annotations

import pytest
import aiosqlite

from onlime.state.store import StateStore, _SCHEMA


# ---------------------------------------------------------------------------
# Fixture: in-memory StateStore
# ---------------------------------------------------------------------------

@pytest.fixture
async def store(tmp_path):
    s = StateStore(tmp_path / "test.db")
    await s.open()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

async def test_schema_idempotent(tmp_path):
    s = StateStore(tmp_path / "idem.db")
    await s.open()
    # second open reuses same connection; create a fresh one against same file
    await s.close()
    s2 = StateStore(tmp_path / "idem.db")
    await s2.open()  # must not raise
    await s2.close()


# ---------------------------------------------------------------------------
# people_timeline
# ---------------------------------------------------------------------------

async def test_insert_timeline_event_and_query(store):
    for i in range(3):
        await store.insert_timeline_event(
            person_name="홍길동",
            event_id=f"evt-{i}",
            source_path=f"/vault/note{i}.md",
            timestamp=f"2026-04-{10 + i:02d}T10:00:00",
            source_type="meeting",
        )
    rows = await store.get_person_timeline("홍길동")
    assert len(rows) == 3
    # DESC order: most recent first
    assert rows[0]["timestamp"] > rows[1]["timestamp"] > rows[2]["timestamp"]


async def test_get_person_stats_aggregates(store):
    # 3 meeting + 2 telegram for 홍길동
    for i in range(3):
        await store.insert_timeline_event(
            person_name="홍길동",
            event_id=None,
            source_path=None,
            timestamp=f"2026-04-0{i+1}T00:00:00",
            source_type="meeting",
        )
    for i in range(2):
        await store.insert_timeline_event(
            person_name="홍길동",
            event_id=None,
            source_path=None,
            timestamp=f"2026-04-1{i+1}T00:00:00",
            source_type="telegram",
        )
    stats = await store.get_person_stats("홍길동")
    assert stats["interaction_count"] == 5
    assert stats["sources"]["meeting"] == 3
    assert stats["sources"]["telegram"] == 2
    assert stats["first_seen"] == "2026-04-01T00:00:00"
    assert stats["last_seen"] == "2026-04-12T00:00:00"


# ---------------------------------------------------------------------------
# action_lifecycle
# ---------------------------------------------------------------------------

async def test_insert_action_default_state(store):
    task_id = await store.insert_action(task_text="리포트 작성")
    rows = await store.get_actions_by_state("open")
    assert any(r["task_id"] == task_id and r["state"] == "open" for r in rows)


async def test_transition_action_success(store):
    task_id = await store.insert_action(task_text="검토")
    result = await store.transition_action(task_id, new_state="in_progress", expected_prior="open")
    assert result is True
    rows = await store.get_actions_by_state("in_progress")
    assert any(r["task_id"] == task_id for r in rows)


async def test_transition_action_optimistic_lock_fail(store):
    task_id = await store.insert_action(task_text="검토2")
    # Wrong expected_prior — should fail
    result = await store.transition_action(task_id, new_state="in_progress", expected_prior="completed")
    assert result is False
    # State must still be 'open'
    rows = await store.get_actions_by_state("open")
    assert any(r["task_id"] == task_id for r in rows)


async def test_transition_action_sets_timestamp(store):
    task_id = await store.insert_action(task_text="완료 테스트")
    await store.transition_action(task_id, new_state="completed", expected_prior="open")
    cursor = await store.db.execute(
        "SELECT completed_at FROM action_lifecycle WHERE task_id = ?", (task_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["completed_at"] is not None


async def test_get_overdue_actions(store):
    # 3 overdue (due in the past), 1 future
    for i in range(3):
        await store.insert_action(
            task_text=f"overdue-{i}",
            due_at="2020-01-01T00:00:00",
        )
    await store.insert_action(task_text="future", due_at="2099-01-01T00:00:00")
    overdue = await store.get_overdue_actions(hours=1)
    assert len(overdue) == 3
    assert all(r["due_at"] == "2020-01-01T00:00:00" for r in overdue)


# ---------------------------------------------------------------------------
# synthesis_cache
# ---------------------------------------------------------------------------

async def test_synthesis_cache_hit_increments_count(store):
    await store.set_synthesis_cache(
        cache_id="c1",
        topic="AI당",
        scope_json="{}",
        output_md="# 결과",
        source_paths_json="[]",
        source_count=2,
        token_count_input=100,
        token_count_output=50,
        model="claude-sonnet-4-6",
    )
    await store.get_synthesis_cache("c1")
    await store.get_synthesis_cache("c1")
    cursor = await store.db.execute("SELECT hit_count FROM synthesis_cache WHERE id='c1'")
    row = await cursor.fetchone()
    assert row["hit_count"] == 2


async def test_prune_synthesis_cache_age_filter(store):
    # Insert an "old" entry by inserting then manually back-dating created_at
    await store.set_synthesis_cache(
        cache_id="old",
        topic="old-topic",
        scope_json="{}",
        output_md="old",
        source_paths_json="[]",
        source_count=1,
        token_count_input=None,
        token_count_output=None,
        model=None,
    )
    await store.db.execute(
        "UPDATE synthesis_cache SET created_at = '2020-01-01T00:00:00' WHERE id = 'old'"
    )
    await store.db.commit()

    await store.set_synthesis_cache(
        cache_id="new",
        topic="new-topic",
        scope_json="{}",
        output_md="new",
        source_paths_json="[]",
        source_count=1,
        token_count_input=None,
        token_count_output=None,
        model=None,
    )

    deleted = await store.prune_synthesis_cache(max_age_hours=1)
    assert deleted == 1

    remaining = await store.get_synthesis_cache("new")
    assert remaining is not None
    gone = await store.get_synthesis_cache("old")
    assert gone is None


async def test_check_constraint_rejects_bad_state(store):
    with pytest.raises(aiosqlite.IntegrityError):
        await store.db.execute(
            "INSERT INTO action_lifecycle (task_text, state) VALUES (?, ?)",
            ("bad", "foobar"),
        )
        await store.db.commit()
