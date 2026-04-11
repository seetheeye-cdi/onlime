"""Tests for new assistant tools: get_person_profile, synthesize_topic, manage_tasks extensions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from onlime.assistant import (
    _tool_get_person_profile,
    _tool_manage_tasks,
    _tool_synthesize_topic,
)
from onlime.processors.action_lifecycle import InvalidTransitionError


# ---------------------------------------------------------------------------
# get_person_profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_person_profile_disabled_returns_message():
    result = await _tool_get_person_profile({"name": "홍길동"}, crm=None)
    assert "비활성화" in result
    assert "people_crm" in result


@pytest.mark.asyncio
async def test_get_person_profile_not_found():
    crm = MagicMock()
    crm.get_person_profile = AsyncMock(return_value=None)
    result = await _tool_get_person_profile({"name": "없는사람"}, crm=crm)
    assert "찾지 못했습니다" in result
    assert "없는사람" in result


@pytest.mark.asyncio
async def test_get_person_profile_happy_path():
    from onlime.processors.people_crm import PersonRecord

    record = PersonRecord(
        canonical_name="홍길동",
        display_name="홍길동",
        wikilink="[[홍길동]]",
        interaction_count=5,
        first_seen="2026-01-01T00:00:00",
        last_seen="2026-04-01T00:00:00",
    )
    pending = [{"task_text": "미팅 준비", "state": "open", "due_at": None}]

    crm = MagicMock()
    crm.get_person_profile = AsyncMock(return_value=record)
    crm.get_pending_actions_for_person = AsyncMock(return_value=pending)

    with patch(
        "onlime.outputs.people_profile.render_people_profile_section",
        return_value="## Onlime 자동 기록\n총 상호작용: 5회\n",
    ) as mock_render:
        result = await _tool_get_person_profile({"name": "홍길동"}, crm=crm)

    mock_render.assert_called_once_with(record, pending_actions=pending)
    assert "Onlime 자동 기록" in result


@pytest.mark.asyncio
async def test_get_person_profile_empty_name():
    crm = MagicMock()
    result = await _tool_get_person_profile({"name": "  "}, crm=crm)
    assert "이름" in result


@pytest.mark.asyncio
async def test_get_person_profile_exception_returns_error():
    crm = MagicMock()
    crm.get_person_profile = AsyncMock(side_effect=RuntimeError("db down"))
    result = await _tool_get_person_profile({"name": "홍길동"}, crm=crm)
    assert "오류" in result


# ---------------------------------------------------------------------------
# synthesize_topic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_topic_disabled():
    result = await _tool_synthesize_topic({"topic": "AI당"}, synthesizer=None)
    assert "비활성화" in result
    assert "synthesis" in result


@pytest.mark.asyncio
async def test_synthesize_topic_happy_path():
    from onlime.processors.synthesizer import SynthesisResult, SynthesisScope, SourceNote

    mock_result = SynthesisResult(
        topic="AI당",
        scope=SynthesisScope(),
        output_md="AI당은 24개월 로드맵을 가진 정당이다.",
        sources=[SourceNote(path="/vault/AI당.md", title="AI당", timestamp=None, content="")],
        token_count_input=100,
        token_count_output=50,
        cached=False,
    )

    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=mock_result)

    result = await _tool_synthesize_topic({"topic": "AI당"}, synthesizer=synthesizer)

    assert "AI당 통합 브리프" in result
    assert "AI당은 24개월 로드맵" in result
    assert "참조" in result
    assert "[[AI당]]" in result


@pytest.mark.asyncio
async def test_synthesize_topic_with_scope_fields():
    from onlime.processors.synthesizer import SynthesisResult, SynthesisScope, SourceNote

    mock_result = SynthesisResult(
        topic="더해커톤",
        scope=SynthesisScope(),
        output_md="더해커톤 요약.",
        sources=[],
        token_count_input=10,
        token_count_output=5,
        cached=False,
    )

    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=mock_result)

    params = {
        "topic": "더해커톤",
        "time_range_start": "2026-01-01",
        "time_range_end": "2026-04-01",
        "person_filter": ["양승현", "최동인"],
        "max_sources": 10,
    }
    await _tool_synthesize_topic(params, synthesizer=synthesizer)

    synthesizer.synthesize.assert_called_once()
    call_args = synthesizer.synthesize.call_args
    scope: SynthesisScope = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["scope"]
    assert scope.time_range == ("2026-01-01", "2026-04-01")
    assert scope.person_filter == ["양승현", "최동인"]
    assert scope.max_sources == 10


@pytest.mark.asyncio
async def test_synthesize_topic_cached_marker():
    from onlime.processors.synthesizer import SynthesisResult, SynthesisScope

    mock_result = SynthesisResult(
        topic="보로메오",
        scope=SynthesisScope(),
        output_md="보로메오 법률 인프라.",
        sources=[],
        token_count_input=0,
        token_count_output=0,
        cached=True,
    )

    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=mock_result)

    result = await _tool_synthesize_topic({"topic": "보로메오"}, synthesizer=synthesizer)
    assert "(캐시)" in result


@pytest.mark.asyncio
async def test_synthesize_topic_empty_topic():
    synthesizer = MagicMock()
    result = await _tool_synthesize_topic({"topic": ""}, synthesizer=synthesizer)
    assert "주제" in result


@pytest.mark.asyncio
async def test_synthesize_topic_exception_returns_error():
    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(side_effect=RuntimeError("llm error"))
    result = await _tool_synthesize_topic({"topic": "테스트"}, synthesizer=synthesizer)
    assert "오류" in result


# ---------------------------------------------------------------------------
# manage_tasks — list_overdue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manage_tasks_list_overdue_disabled():
    result = await _tool_manage_tasks(
        {"action": "list_overdue"}, store=None, action_lifecycle=None
    )
    assert "비활성화" in result
    assert "action_lifecycle" in result


@pytest.mark.asyncio
async def test_manage_tasks_list_overdue_happy():
    rows = [
        {"task_id": 1, "state": "open", "task_text": "이메일 답장", "owner": None},
        {"task_id": 2, "state": "in_progress", "task_text": "미팅 준비", "owner": "홍길동"},
    ]
    lifecycle = MagicMock()
    lifecycle.get_overdue = AsyncMock(return_value=rows)

    result = await _tool_manage_tasks(
        {"action": "list_overdue", "hours": 48}, store=None, action_lifecycle=lifecycle
    )

    assert "이메일 답장" in result
    assert "미팅 준비" in result
    assert "#1" in result
    assert "#2" in result
    lifecycle.get_overdue.assert_called_once_with(hours=48)


@pytest.mark.asyncio
async def test_manage_tasks_list_overdue_empty():
    lifecycle = MagicMock()
    lifecycle.get_overdue = AsyncMock(return_value=[])

    result = await _tool_manage_tasks(
        {"action": "list_overdue"}, store=None, action_lifecycle=lifecycle
    )
    assert "없습니다" in result


# ---------------------------------------------------------------------------
# manage_tasks — transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manage_tasks_transition_disabled():
    result = await _tool_manage_tasks(
        {"action": "transition", "task_id": 1, "new_state": "completed", "expected_prior": "open"},
        store=None,
        action_lifecycle=None,
    )
    assert "비활성화" in result


@pytest.mark.asyncio
async def test_manage_tasks_transition_happy():
    lifecycle = MagicMock()
    lifecycle.transition = AsyncMock(return_value=True)

    result = await _tool_manage_tasks(
        {"action": "transition", "task_id": 3, "new_state": "completed", "expected_prior": "open"},
        store=None,
        action_lifecycle=lifecycle,
    )

    assert "#3" in result
    assert "완료" in result
    lifecycle.transition.assert_called_once_with(
        3, new_state="completed", expected_prior="open", actor="assistant"
    )


@pytest.mark.asyncio
async def test_manage_tasks_transition_optimistic_fail():
    lifecycle = MagicMock()
    lifecycle.transition = AsyncMock(return_value=False)

    result = await _tool_manage_tasks(
        {
            "action": "transition",
            "task_id": 5,
            "new_state": "completed",
            "expected_prior": "in_progress",
        },
        store=None,
        action_lifecycle=lifecycle,
    )

    assert "전환 실패" in result
    assert "#5" in result


@pytest.mark.asyncio
async def test_manage_tasks_transition_missing_args():
    lifecycle = MagicMock()

    result = await _tool_manage_tasks(
        {"action": "transition", "new_state": "completed"},
        store=None,
        action_lifecycle=lifecycle,
    )
    assert "필요합니다" in result


@pytest.mark.asyncio
async def test_manage_tasks_transition_invalid_raises():
    lifecycle = MagicMock()
    lifecycle.transition = AsyncMock(side_effect=InvalidTransitionError("completed → open not allowed"))

    result = await _tool_manage_tasks(
        {
            "action": "transition",
            "task_id": 7,
            "new_state": "open",
            "expected_prior": "completed",
        },
        store=None,
        action_lifecycle=lifecycle,
    )
    assert "실패" in result
    assert "not allowed" in result or "전환" in result


# ---------------------------------------------------------------------------
# manage_tasks — legacy actions still work with store=None guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manage_tasks_list_requires_store():
    result = await _tool_manage_tasks({"action": "list"}, store=None)
    assert "초기화" in result


@pytest.mark.asyncio
async def test_manage_tasks_complete_requires_store():
    result = await _tool_manage_tasks({"action": "complete", "task_id": 1}, store=None)
    assert "초기화" in result
