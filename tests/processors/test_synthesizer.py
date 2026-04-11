"""Tests for Synthesizer — extensive mocking since Claude + hybrid search are external."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onlime.processors.synthesizer import (
    CACHE_TTL_HOURS,
    CHARS_PER_TOKEN,
    CHUNK_SIZE_TOKENS,
    MAX_SOURCES_DEFAULT,
    TOKEN_BUDGET_INPUT,
    SourceNote,
    SynthesisResult,
    SynthesisScope,
    Synthesizer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClaude:
    def __init__(self, response_text: str = "fake response") -> None:
        self.messages = MagicMock()
        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text=response_text)]
        fake_resp.usage = MagicMock(input_tokens=100, output_tokens=50)
        self.messages.create = AsyncMock(return_value=fake_resp)


def _make_store(*, cache_row: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.get_synthesis_cache = AsyncMock(return_value=cache_row)
    store.set_synthesis_cache = AsyncMock(return_value=None)
    # Expose a fake db for invalidate_cache_for_path tests
    fake_cursor = MagicMock()
    fake_cursor.rowcount = 2
    fake_db = MagicMock()
    fake_db.execute = AsyncMock(return_value=fake_cursor)
    fake_db.commit = AsyncMock(return_value=None)
    store.db = fake_db
    return store


def _make_hybrid(results: list[dict] | None = None) -> MagicMock:
    hybrid = MagicMock()
    hybrid.search = AsyncMock(return_value=results or [])
    return hybrid


def _make_synthesizer(
    *,
    store: MagicMock | None = None,
    hybrid: MagicMock | None = None,
    graph: MagicMock | None = None,
    claude: FakeClaude | None = None,
    vault_root: Path | None = None,
) -> Synthesizer:
    return Synthesizer(
        store=store or _make_store(),
        hybrid=hybrid or _make_hybrid(),
        graph=graph,
        name_index=MagicMock(),
        vault_root=vault_root or Path("/tmp/fake_vault"),
        claude_client=claude or FakeClaude(),
    )


def _fresh_cache_row(topic: str = "test", output_md: str = "cached output") -> dict:
    scope = SynthesisScope()
    return {
        "id": "abc123",
        "topic": topic,
        "scope_json": json.dumps(scope.to_dict()),
        "output_md": output_md,
        "source_paths_json": json.dumps(["/vault/note1.md"]),
        "source_count": 1,
        "token_count_input": 100,
        "token_count_output": 50,
        "model": "claude-sonnet-4-6",
        "created_at": datetime.now().isoformat(),
        "last_used_at": datetime.now().isoformat(),
        "hit_count": 0,
    }


# ---------------------------------------------------------------------------
# D1: SynthesisScope unit tests
# ---------------------------------------------------------------------------


def test_scope_cache_key_deterministic() -> None:
    scope = SynthesisScope(person_filter=["alice", "bob"], max_sources=10)
    key1 = scope.cache_key("AI당")
    key2 = scope.cache_key("AI당")
    assert key1 == key2
    assert len(key1) == 64  # sha256 hex

    other_scope = SynthesisScope(person_filter=["alice"], max_sources=10)
    key3 = other_scope.cache_key("AI당")
    assert key1 != key3

    key4 = scope.cache_key("다른 주제")
    assert key1 != key4


def test_scope_to_dict_sorts_lists() -> None:
    scope = SynthesisScope(
        person_filter=["charlie", "alice", "bob"],
        project_filter=["z_proj", "a_proj"],
        tag_filter=["태그B", "태그A"],
    )
    d = scope.to_dict()
    assert d["person_filter"] == ["alice", "bob", "charlie"]
    assert d["project_filter"] == ["a_proj", "z_proj"]
    assert d["tag_filter"] == ["태그A", "태그B"]


# ---------------------------------------------------------------------------
# D2: Cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_cache_hit() -> None:
    row = _fresh_cache_row(topic="AI당", output_md="## cached result")
    store = _make_store(cache_row=row)
    claude = FakeClaude()
    synth = _make_synthesizer(store=store, claude=claude)

    result = await synth.synthesize("AI당")

    assert result.cached is True
    assert result.output_md == "## cached result"
    assert result.topic == "AI당"
    claude.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# D3: Cache miss → full pipeline → save
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_cache_miss_then_save(tmp_path: Path) -> None:
    note = tmp_path / "note1.md"
    note.write_text("# Test Note\nsome content here", encoding="utf-8")

    store = _make_store(cache_row=None)
    hybrid = _make_hybrid(results=[{"path": str(note), "rrf_score": 0.9}])
    claude = FakeClaude("synthesized result")
    synth = _make_synthesizer(store=store, hybrid=hybrid, claude=claude, vault_root=tmp_path)

    result = await synth.synthesize("test topic")

    assert result.cached is False
    store.set_synthesis_cache.assert_called_once()
    call_kwargs = store.set_synthesis_cache.call_args.kwargs
    assert call_kwargs["topic"] == "test topic"
    assert "synthesized result" in call_kwargs["output_md"] or len(call_kwargs["output_md"]) > 0


# ---------------------------------------------------------------------------
# D4: Empty candidates → empty result, Claude not called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_empty_candidates() -> None:
    store = _make_store(cache_row=None)
    hybrid = _make_hybrid(results=[])
    claude = FakeClaude()
    synth = _make_synthesizer(store=store, hybrid=hybrid, claude=claude)

    result = await synth.synthesize("nonexistent topic")

    assert result.cached is False
    assert "찾지 못했습니다" in result.output_md
    assert result.sources == []
    claude.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# D5: Map-reduce triggered on large input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_map_reduce_triggered_on_large_input(tmp_path: Path) -> None:
    # Create sources whose total chars exceed TOKEN_BUDGET_INPUT * CHARS_PER_TOKEN
    target_chars = TOKEN_BUDGET_INPUT * CHARS_PER_TOKEN + 1000
    big_content = "가" * target_chars
    note = tmp_path / "big_note.md"
    note.write_text(big_content, encoding="utf-8")

    store = _make_store(cache_row=None)
    hybrid = _make_hybrid(results=[{"path": str(note), "rrf_score": 0.9}])
    claude = FakeClaude("chunk result")
    synth = _make_synthesizer(store=store, hybrid=hybrid, claude=claude, vault_root=tmp_path)

    with patch.object(synth, "_map_reduce_synthesize", new=AsyncMock(return_value=("map_reduce output", 200, 100))) as mock_mr:
        with patch.object(synth, "_single_shot_synthesize", new=AsyncMock(return_value=("single output", 100, 50))) as mock_ss:
            result = await synth.synthesize("big topic", force_refresh=True)
            mock_mr.assert_called_once()
            mock_ss.assert_not_called()


# ---------------------------------------------------------------------------
# D6: Single-shot on small input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_shot_on_small_input(tmp_path: Path) -> None:
    note = tmp_path / "small_note.md"
    note.write_text("짧은 내용", encoding="utf-8")

    store = _make_store(cache_row=None)
    hybrid = _make_hybrid(results=[{"path": str(note), "rrf_score": 0.9}])
    claude = FakeClaude("single shot output")
    synth = _make_synthesizer(store=store, hybrid=hybrid, claude=claude, vault_root=tmp_path)

    with patch.object(synth, "_map_reduce_synthesize", new=AsyncMock(return_value=("mr", 200, 100))) as mock_mr:
        with patch.object(synth, "_single_shot_synthesize", new=AsyncMock(return_value=("ss", 100, 50))) as mock_ss:
            result = await synth.synthesize("small topic", force_refresh=True)
            mock_ss.assert_called_once()
            mock_mr.assert_not_called()


# ---------------------------------------------------------------------------
# D7: _apply_scope_filters — time range
# ---------------------------------------------------------------------------


def test_apply_scope_filters_time_range() -> None:
    synth = _make_synthesizer()
    candidates = [
        {"path": "a.md", "timestamp": "2024-01-10T00:00:00"},
        {"path": "b.md", "timestamp": "2024-03-15T00:00:00"},
        {"path": "c.md", "timestamp": "2024-05-01T00:00:00"},
    ]
    scope = SynthesisScope(time_range=("2024-02-01T00:00:00", "2024-04-01T00:00:00"))
    result = synth._apply_scope_filters(candidates, scope)
    paths = [r["path"] for r in result]
    assert "a.md" not in paths
    assert "b.md" in paths
    assert "c.md" not in paths


# ---------------------------------------------------------------------------
# D8: _apply_scope_filters — person filter
# ---------------------------------------------------------------------------


def test_apply_scope_filters_person_filter() -> None:
    synth = _make_synthesizer()
    candidates = [
        {"path": "1.INPUT/People/김철수.md", "snippet": "meeting notes"},
        {"path": "2.OUTPUT/Daily/2024-01-01.md", "snippet": "general notes"},
        {"path": "1.INPUT/People/이영희.md", "snippet": "김철수 mentioned"},
    ]
    scope = SynthesisScope(person_filter=["김철수"])
    result = synth._apply_scope_filters(candidates, scope)
    paths = [r["path"] for r in result]
    assert "1.INPUT/People/김철수.md" in paths
    assert "1.INPUT/People/이영희.md" in paths   # snippet contains 김철수
    assert "2.OUTPUT/Daily/2024-01-01.md" not in paths


# ---------------------------------------------------------------------------
# D9: Cache TTL expired → _check_cache returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_ttl_expired_returns_none() -> None:
    old_time = (datetime.now() - timedelta(hours=CACHE_TTL_HOURS + 6)).isoformat()
    row = _fresh_cache_row()
    row["created_at"] = old_time

    store = _make_store(cache_row=row)
    synth = _make_synthesizer(store=store)

    result = await synth._check_cache("any_id")
    assert result is None


# ---------------------------------------------------------------------------
# D10: invalidate_cache_for_path — DELETE called with LIKE pattern
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_cache_for_path_deletes_matching() -> None:
    store = _make_store()
    synth = _make_synthesizer(store=store)

    deleted = await synth.invalidate_cache_for_path("/vault/some_note.md")

    store.db.execute.assert_called_once()
    call_args = store.db.execute.call_args
    sql = call_args[0][0]
    params = call_args[0][1]
    assert "DELETE FROM synthesis_cache" in sql
    assert "LIKE" in sql
    assert "%/vault/some_note.md%" in params[0]
    assert deleted == 2  # rowcount from fake cursor


# ---------------------------------------------------------------------------
# D11: _post_process calls both helpers
# ---------------------------------------------------------------------------


def test_post_process_calls_helpers() -> None:
    # _post_process imports helpers inline; patch at the source module level.
    synth = _make_synthesizer()
    input_text = "테스트 문장입니다. 두 번째 문장입니다."

    with patch(
        "onlime.processors.name_resolver.resolve_wikilinks",
        return_value=input_text,
    ) as mock_rw:
        with patch(
            "onlime.processors.summarizer.format_one_sentence_per_line",
            return_value=input_text,
        ) as mock_spl:
            result = synth._post_process(input_text)

    mock_rw.assert_called_once()
    mock_spl.assert_called_once()
    assert result == input_text


# ---------------------------------------------------------------------------
# D12: _split_into_chunks respects max_chars boundary
# ---------------------------------------------------------------------------


def test_split_into_chunks_respects_boundary() -> None:
    # Each source is 100 chars. max_chars=250 allows first chunk to hold 2
    # (0+100=100 fits, 100+100=200 fits, 200+100=300 > 250 → new chunk).
    sources = [
        SourceNote(path="a.md", title="a", timestamp=None, content="x" * 100),
        SourceNote(path="b.md", title="b", timestamp=None, content="x" * 100),
        SourceNote(path="c.md", title="c", timestamp=None, content="x" * 100),
    ]
    chunks = Synthesizer._split_into_chunks(sources, max_chars=250)
    assert len(chunks) == 2
    assert len(chunks[0]) == 2
    assert len(chunks[1]) == 1


def test_split_into_chunks_single_chunk_when_fits() -> None:
    sources = [
        SourceNote(path="a.md", title="a", timestamp=None, content="x" * 50),
        SourceNote(path="b.md", title="b", timestamp=None, content="x" * 50),
    ]
    chunks = Synthesizer._split_into_chunks(sources, max_chars=200)
    assert len(chunks) == 1
    assert len(chunks[0]) == 2
