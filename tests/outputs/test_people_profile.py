"""Tests for src/onlime/outputs/people_profile.py"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from onlime.outputs.people_profile import (
    END_MARKER,
    START_MARKER,
    _fmt_date,
    render_people_profile_section,
    refresh_people_profiles,
    upsert_auto_section,
)
from onlime.processors.people_crm import PersonRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(**kwargs) -> PersonRecord:
    defaults = dict(
        canonical_name="홍길동",
        display_name="홍길동",
        wikilink="[[홍길동]]",
        aliases=[],
        kakao_name=None,
        telegram_username=None,
        first_seen=None,
        last_seen=None,
        interaction_count=0,
        sources={},
        recent_relations=[],
        vault_profile_path=None,
    )
    defaults.update(kwargs)
    return PersonRecord(**defaults)


def _make_crm(record: PersonRecord | None = None, pending: list | None = None) -> AsyncMock:
    crm = AsyncMock()
    crm.get_person_profile = AsyncMock(return_value=record)
    crm.get_pending_actions_for_person = AsyncMock(return_value=pending or [])
    return crm


# ---------------------------------------------------------------------------
# render_people_profile_section tests
# ---------------------------------------------------------------------------

def test_render_section_minimal():
    record = _make_record(interaction_count=3)
    out = render_people_profile_section(record)
    assert "## Onlime 자동 기록" in out
    assert "- 총 상호작용: 3회" in out


def test_render_section_full():
    record = _make_record(
        aliases=["길동이", "GD"],
        kakao_name="카카오홍",
        telegram_username="hong_gd",
        first_seen="2025-01-01T10:00:00",
        last_seen="2026-04-10T09:30:00",
        interaction_count=42,
        sources={"telegram": 30, "kakao": 12},
        recent_relations=["mention", "meeting"],
    )
    out = render_people_profile_section(record)
    assert "### 식별자" in out
    assert "- 별명: 길동이, GD" in out
    assert "- 카카오: 카카오홍" in out
    assert "- 텔레그램: @hong_gd" in out
    assert "### 상호작용 통계" in out
    assert "- 총 상호작용: 42회" in out
    assert "- 첫 기록: 2025-01-01" in out
    assert "- 최근 기록: 2026-04-10" in out
    assert "telegram 30회" in out
    assert "### 최근 접점" in out
    assert "- mention" in out
    assert "- meeting" in out


def test_render_section_with_pending_actions():
    record = _make_record()
    actions = [
        {"task_text": "보고서 작성", "state": "open", "due_at": "2026-04-15T00:00:00"},
        {"task_text": "이메일 답변", "state": "in_progress", "due_at": None},
    ]
    out = render_people_profile_section(record, pending_actions=actions)
    assert "### 대기 중인 할 일" in out
    assert "[open] 보고서 작성" in out
    assert "due 2026-04-15" in out
    assert "[in_progress] 이메일 답변" in out


def test_render_section_empty_aliases_hidden():
    record = _make_record(aliases=[], kakao_name=None, telegram_username=None)
    out = render_people_profile_section(record)
    assert "### 식별자" not in out


# ---------------------------------------------------------------------------
# upsert_auto_section tests
# ---------------------------------------------------------------------------

def test_upsert_new_file(tmp_path: Path):
    target = tmp_path / "People" / "홍길동.md"
    rendered = "## Onlime 자동 기록\n- 총 상호작용: 5회\n"
    result = upsert_auto_section(target, rendered)
    assert result is True
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert START_MARKER in text
    assert END_MARKER in text
    assert "총 상호작용: 5회" in text


def test_upsert_no_markers_appends(tmp_path: Path):
    target = tmp_path / "홍길동.md"
    original = "# 홍길동\n\n사용자 작성 내용.\n"
    target.write_text(original, encoding="utf-8")
    rendered = "## Onlime 자동 기록\n- 총 상호작용: 1회\n"
    result = upsert_auto_section(target, rendered)
    assert result is True
    text = target.read_text(encoding="utf-8")
    assert "사용자 작성 내용." in text
    assert START_MARKER in text
    assert END_MARKER in text
    # Original must appear before the marker block
    assert text.index("사용자 작성 내용.") < text.index(START_MARKER)


def test_upsert_with_markers_replaces(tmp_path: Path):
    target = tmp_path / "홍길동.md"
    old_block = f"{START_MARKER}\n## Onlime 자동 기록\n- 총 상호작용: 1회\n{END_MARKER}"
    original = f"# 홍길동\n\n{old_block}\n\n사용자 후기 내용.\n"
    target.write_text(original, encoding="utf-8")
    rendered = "## Onlime 자동 기록\n- 총 상호작용: 99회\n"
    result = upsert_auto_section(target, rendered)
    assert result is True
    text = target.read_text(encoding="utf-8")
    assert "총 상호작용: 99회" in text
    assert "총 상호작용: 1회" not in text
    assert "사용자 후기 내용." in text


def test_upsert_preserves_user_content_before_markers(tmp_path: Path):
    target = tmp_path / "김철수.md"
    user_body = "# 김철수\n\n## 소개\n엄청난 내용이 여기 있습니다.\n\n## 프로젝트\n- 프로젝트 A\n- 프로젝트 B\n\n"
    old_auto = f"{START_MARKER}\n오래된 내용\n{END_MARKER}\n"
    target.write_text(user_body + old_auto, encoding="utf-8")
    rendered = "새로운 자동 내용\n"
    result = upsert_auto_section(target, rendered)
    assert result is True
    text = target.read_text(encoding="utf-8")
    assert "엄청난 내용이 여기 있습니다." in text
    assert "프로젝트 A" in text
    assert "새로운 자동 내용" in text
    assert "오래된 내용" not in text
    # User body intact before marker
    assert text.index("## 소개") < text.index(START_MARKER)


def test_upsert_unchanged_returns_false(tmp_path: Path):
    target = tmp_path / "홍길동.md"
    rendered = "## Onlime 자동 기록\n- 총 상호작용: 5회\n"
    # Write once
    upsert_auto_section(target, rendered)
    # Write identical content again — should return False
    result = upsert_auto_section(target, rendered)
    assert result is False


def test_upsert_atomic_no_partial_file(tmp_path: Path):
    target = tmp_path / "홍길동.md"
    rendered = "## Onlime 자동 기록\n- 총 상호작용: 7회\n"
    upsert_auto_section(target, rendered)
    # After write, no .tmp file should linger
    tmp_file = target.with_suffix(target.suffix + ".tmp")
    assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# _fmt_date tests
# ---------------------------------------------------------------------------

def test_fmt_date_iso():
    assert _fmt_date("2026-04-10T09:30:00") == "2026-04-10"
    assert _fmt_date("2025-01-01T00:00:00.000000") == "2025-01-01"


def test_fmt_date_invalid_fallback():
    assert _fmt_date("garbage-string") == "garbage-st"  # first 10 chars
    assert _fmt_date("") == ""
    assert _fmt_date(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# refresh_people_profiles tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_people_profiles_mtime_filter(tmp_path: Path):
    """Only files with mtime >= cutoff should be processed."""
    people_dir = tmp_path / "1.INPUT" / "People"
    people_dir.mkdir(parents=True)

    # Create 3 files
    recent = people_dir / "홍길동.md"
    recent.write_text("# 홍길동\n", encoding="utf-8")

    old1 = people_dir / "김철수.md"
    old1.write_text("# 김철수\n", encoding="utf-8")

    old2 = people_dir / "이영희.md"
    old2.write_text("# 이영희\n", encoding="utf-8")

    # Set old files to a past mtime (3 hours ago)
    past_ts = (datetime.now() - timedelta(hours=3)).timestamp()
    import os
    os.utime(old1, (past_ts, past_ts))
    os.utime(old2, (past_ts, past_ts))
    # recent file keeps its current mtime (just created)

    record = _make_record(canonical_name="홍길동", display_name="홍길동")
    crm = _make_crm(record=record)

    cutoff = datetime.now() - timedelta(hours=2)
    updated = await refresh_people_profiles(crm, tmp_path, modified_since=cutoff)

    # Only the recent file passes the mtime filter
    assert updated == 1
    assert crm.get_person_profile.call_count == 1
    called_stem = crm.get_person_profile.call_args[0][0]
    assert called_stem == "홍길동"


@pytest.mark.asyncio
async def test_refresh_people_profiles_skips_missing_dirs(tmp_path: Path):
    """vault_root with no People dirs → no crash, returns 0."""
    crm = _make_crm()
    updated = await refresh_people_profiles(crm, tmp_path)
    assert updated == 0
    crm.get_person_profile.assert_not_called()
