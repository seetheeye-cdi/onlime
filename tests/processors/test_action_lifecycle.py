"""Tests for ActionLifecycle FSM and ActionEscalatorTask."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onlime.processors.action_lifecycle import (
    ALLOWED_TRANSITIONS,
    ActionLifecycle,
    ActionState,
    InvalidTransitionError,
    TERMINAL_STATES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(
    insert_return: int = 1,
    transition_return: bool = True,
    actions_by_state: list[dict] | None = None,
    overdue: list[dict] | None = None,
) -> MagicMock:
    store = MagicMock()
    store.insert_action = AsyncMock(return_value=insert_return)
    store.transition_action = AsyncMock(return_value=transition_return)
    store.get_actions_by_state = AsyncMock(return_value=actions_by_state or [])
    store.get_overdue_actions = AsyncMock(return_value=overdue or [])
    store.get_connector_state = AsyncMock(return_value=None)
    store.save_connector_state = AsyncMock()
    return store


def _make_resolver(resolved: str | None = "canonical_owner") -> MagicMock:
    resolver = MagicMock()
    resolver.resolve = MagicMock(return_value=resolved)
    return resolver


def _make_lc(store=None, resolver=None) -> ActionLifecycle:
    return ActionLifecycle(
        store=store or _make_store(),
        resolver=resolver or _make_resolver(),
    )


# ---------------------------------------------------------------------------
# D4.1 — transition table matches spec
# ---------------------------------------------------------------------------

def test_allowed_transitions_table():
    spec = {
        ActionState.OPEN: {
            ActionState.IN_PROGRESS, ActionState.WAITING_ON_OTHER,
            ActionState.BLOCKED, ActionState.COMPLETED,
            ActionState.CANCELLED, ActionState.ESCALATED,
        },
        ActionState.IN_PROGRESS: {
            ActionState.WAITING_ON_OTHER, ActionState.BLOCKED,
            ActionState.COMPLETED, ActionState.CANCELLED,
        },
        ActionState.WAITING_ON_OTHER: {
            ActionState.IN_PROGRESS, ActionState.BLOCKED,
            ActionState.COMPLETED, ActionState.CANCELLED,
        },
        ActionState.BLOCKED: {
            ActionState.OPEN, ActionState.IN_PROGRESS, ActionState.CANCELLED,
        },
        ActionState.COMPLETED: set(),
        ActionState.CANCELLED: set(),
        ActionState.ESCALATED: {
            ActionState.OPEN, ActionState.IN_PROGRESS,
            ActionState.COMPLETED, ActionState.CANCELLED,
        },
    }
    assert ALLOWED_TRANSITIONS == spec


# ---------------------------------------------------------------------------
# D4.2 — insert resolves owner through PeopleResolver
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_from_extraction_resolves_owner():
    store = _make_store(insert_return=42)
    resolver = _make_resolver(resolved="박도현_개발자")
    lc = _make_lc(store=store, resolver=resolver)

    ids = await lc.insert_from_extraction(
        items=[{"task": "코드 리뷰하기", "owner": "박도현", "due_date": "2026-04-20"}],
        event_id="evt-001",
    )

    assert ids == [42]
    store.insert_action.assert_called_once()
    call_kwargs = store.insert_action.call_args.kwargs
    assert call_kwargs["owner"] == "박도현_개발자"
    assert call_kwargs["task_text"] == "코드 리뷰하기"
    assert call_kwargs["source_event_id"] == "evt-001"


# ---------------------------------------------------------------------------
# D4.3 — '나' owner maps to None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_from_extraction_self_owner_to_none():
    store = _make_store(insert_return=7)
    lc = _make_lc(store=store)

    await lc.insert_from_extraction(
        items=[{"task": "문서 작성", "owner": "나", "due_date": ""}],
        event_id="evt-002",
    )

    call_kwargs = store.insert_action.call_args.kwargs
    assert call_kwargs["owner"] is None


# ---------------------------------------------------------------------------
# D4.4 — unknown priority defaults to 'normal'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_from_extraction_invalid_priority_defaults_normal():
    store = _make_store(insert_return=3)
    lc = _make_lc(store=store)

    await lc.insert_from_extraction(
        items=[{"task": "테스트 작성", "owner": "", "priority": "unknown"}],
        event_id="evt-003",
    )

    call_kwargs = store.insert_action.call_args.kwargs
    assert call_kwargs["priority"] == "normal"


# ---------------------------------------------------------------------------
# D4.5 — empty task string is skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_from_extraction_empty_task_skipped():
    store = _make_store()
    lc = _make_lc(store=store)

    ids = await lc.insert_from_extraction(
        items=[{"task": "   ", "owner": ""}, {"task": "", "owner": ""}],
        event_id="evt-004",
    )

    assert ids == []
    store.insert_action.assert_not_called()


# ---------------------------------------------------------------------------
# D4.6 — transition happy path returns True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_happy_path():
    store = _make_store(transition_return=True)
    lc = _make_lc(store=store)

    result = await lc.transition(
        1,
        new_state=ActionState.IN_PROGRESS,
        expected_prior=ActionState.OPEN,
    )

    assert result is True
    store.transition_action.assert_called_once_with(
        1, new_state="in_progress", expected_prior="open"
    )


# ---------------------------------------------------------------------------
# D4.7 — optimistic lock fail (prior mismatch) returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_optimistic_lock_fail():
    store = _make_store(transition_return=False)
    lc = _make_lc(store=store)

    result = await lc.transition(
        99,
        new_state="in_progress",
        expected_prior="open",
    )

    assert result is False


# ---------------------------------------------------------------------------
# D4.8 — illegal transition raises InvalidTransitionError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_illegal_raises():
    lc = _make_lc()

    with pytest.raises(InvalidTransitionError):
        await lc.transition(
            1,
            new_state=ActionState.OPEN,
            expected_prior=ActionState.COMPLETED,
        )


# ---------------------------------------------------------------------------
# D4.9 — completing triggers _maybe_sync_source_note
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_completed_triggers_sync():
    store = _make_store(transition_return=True, actions_by_state=[
        {"task_id": 5, "task_text": "리포트 제출", "source_note_path": None}
    ])
    lc = _make_lc(store=store)
    lc._maybe_sync_source_note = AsyncMock()

    await lc.transition(
        5,
        new_state=ActionState.COMPLETED,
        expected_prior=ActionState.IN_PROGRESS,
    )

    lc._maybe_sync_source_note.assert_awaited_once_with(5)


# ---------------------------------------------------------------------------
# D4.10 — source note checkbox rewrite
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_source_note_rewrites_checkbox(tmp_path: Path):
    task_text = "문서 최종 검토하기"
    note = tmp_path / "meeting.md"
    note.write_text(f"# 회의\n\n- [ ] {task_text}\n- [ ] 다른 할일\n", encoding="utf-8")

    store = _make_store(
        transition_return=True,
        actions_by_state=[
            {
                "task_id": 10,
                "task_text": task_text,
                "source_note_path": str(note),
            }
        ],
    )
    lc = _make_lc(store=store)

    await lc._maybe_sync_source_note(10)

    content = note.read_text(encoding="utf-8")
    date_str = datetime.now().strftime("%Y-%m-%d")
    assert f"- [x] {task_text}" in content
    assert f"✅ {date_str}" in content
    # other item untouched
    assert "- [ ] 다른 할일" in content


# ---------------------------------------------------------------------------
# D4.11 — missing source_note_path is a no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_source_note_missing_path_noop():
    store = _make_store(
        actions_by_state=[
            {"task_id": 11, "task_text": "할 일", "source_note_path": None}
        ]
    )
    lc = _make_lc(store=store)

    # Should not raise
    await lc._maybe_sync_source_note(11)


# ---------------------------------------------------------------------------
# D4.12 — list_self_pending filters only null-owner rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_self_pending_filters_owner_none():
    open_rows = [
        {"task_id": 1, "owner": None, "state": "open"},
        {"task_id": 2, "owner": "김단영", "state": "open"},
    ]
    inprog_rows = [
        {"task_id": 3, "owner": None, "state": "in_progress"},
        {"task_id": 4, "owner": "박도현", "state": "in_progress"},
    ]

    async def _get_by_state(state, *, owner=None, limit=100):
        if state == "open":
            return open_rows
        if state == "in_progress":
            return inprog_rows
        return []

    store = _make_store()
    store.get_actions_by_state = AsyncMock(side_effect=_get_by_state)
    lc = _make_lc(store=store)

    result = await lc.list_self_pending()

    task_ids = [r["task_id"] for r in result]
    assert 1 in task_ids
    assert 3 in task_ids
    assert 2 not in task_ids
    assert 4 not in task_ids


# ---------------------------------------------------------------------------
# D4.13 — get_overdue wraps store method
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_overdue_wraps_store_method():
    expected = [{"task_id": 99, "task_text": "오래된 작업"}]
    store = _make_store(overdue=expected)
    lc = _make_lc(store=store)

    result = await lc.get_overdue(hours=48, owner="최동인")

    store.get_overdue_actions.assert_called_once_with(hours=48, owner="최동인")
    assert result == expected


# ===========================================================================
# Escalator tests (D5)
# ===========================================================================

from onlime.maintenance.action_escalator import (
    ActionEscalatorTask,
    ESCALATION_HOURS,
    TELEGRAM_MIN_COUNT,
    NUDGE_STATE_KEY,
)


def _make_escalator(
    store=None,
    lifecycle=None,
    vault_root: Path | None = None,
    telegram_sender=None,
    tmp_path: Path | None = None,
) -> ActionEscalatorTask:
    if vault_root is None:
        vault_root = tmp_path or Path("/tmp/fake_vault")
    return ActionEscalatorTask(
        store=store or _make_store(),
        lifecycle=lifecycle or MagicMock(),
        vault_root=vault_root,
        telegram_sender=telegram_sender,
    )


def _patch_flag(enabled: bool):
    mock_settings = MagicMock()
    mock_settings.feature_flags.action_lifecycle = enabled
    return patch(
        "onlime.maintenance.action_escalator.get_settings",
        return_value=mock_settings,
    )


# ---------------------------------------------------------------------------
# D5.1 — escalator marks overdue rows as escalated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalator_marks_overdue(tmp_path: Path):
    overdue_rows = [
        {"task_id": 1, "task_text": "작업 A", "owner": None, "due_at": "2026-04-01"},
        {"task_id": 2, "task_text": "작업 B", "owner": "김단영", "due_at": "2026-04-02"},
    ]
    store = _make_store(overdue=overdue_rows)

    lc = MagicMock()
    lc.transition = AsyncMock(return_value=True)

    escalator = _make_escalator(store=store, lifecycle=lc, vault_root=tmp_path)

    with _patch_flag(True):
        await escalator.run_once()

    assert lc.transition.call_count == 2
    for call in lc.transition.call_args_list:
        assert call.kwargs["new_state"] == "escalated"
        assert call.kwargs["expected_prior"] == "open"
        assert call.kwargs["actor"] == "escalator"


# ---------------------------------------------------------------------------
# D5.2 — telegram digest sent when ≥3 self-owned escalated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalator_telegram_digest_threshold(tmp_path: Path):
    overdue_rows = [
        {"task_id": i, "task_text": f"작업 {i}", "owner": None, "due_at": "2026-04-01"}
        for i in range(1, 4)
    ]
    store = _make_store(overdue=overdue_rows)
    store.get_connector_state = AsyncMock(return_value=None)
    store.save_connector_state = AsyncMock()

    lc = MagicMock()
    lc.transition = AsyncMock(return_value=True)

    tg = MagicMock()
    tg.send_message = AsyncMock()

    escalator = _make_escalator(
        store=store, lifecycle=lc, vault_root=tmp_path, telegram_sender=tg
    )

    with _patch_flag(True):
        await escalator.run_once()

    tg.send_message.assert_awaited_once()
    sent_text = tg.send_message.call_args[0][0]
    assert "3" in sent_text
    store.save_connector_state.assert_awaited_once()


# ---------------------------------------------------------------------------
# D5.3 — cooldown blocks second nudge within 24h
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalator_cooldown_blocks_second_nudge(tmp_path: Path):
    overdue_rows = [
        {"task_id": i, "task_text": f"작업 {i}", "owner": None, "due_at": "2026-04-01"}
        for i in range(1, 4)
    ]
    store = _make_store(overdue=overdue_rows)
    # last_nudge is 1 hour ago — within cooldown
    recent_nudge = (datetime.now() - timedelta(hours=1)).isoformat()
    store.get_connector_state = AsyncMock(
        return_value={"last_nudge": recent_nudge}
    )
    store.save_connector_state = AsyncMock()

    lc = MagicMock()
    lc.transition = AsyncMock(return_value=True)

    tg = MagicMock()
    tg.send_message = AsyncMock()

    escalator = _make_escalator(
        store=store, lifecycle=lc, vault_root=tmp_path, telegram_sender=tg
    )

    with _patch_flag(True):
        await escalator.run_once()

    # Telegram NOT called — still in cooldown
    tg.send_message.assert_not_awaited()
    store.save_connector_state.assert_not_awaited()
