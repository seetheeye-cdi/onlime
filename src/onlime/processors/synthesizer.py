"""Multi-note knowledge synthesis — hybrid search → LLM digest → cache."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

import structlog

from onlime.config import get_settings

if TYPE_CHECKING:
    from onlime.state.store import StateStore
    from onlime.search.hybrid import HybridSearch
    from onlime.search.graph import VaultGraph
    from onlime.processors.name_resolver import VaultNameIndex

logger = structlog.get_logger()

# Constants
MAX_SOURCES_DEFAULT = 20
TOKEN_BUDGET_INPUT = 150_000       # Claude 200k context, reserve 50k for headroom
CHUNK_SIZE_TOKENS = 40_000         # map-reduce chunk size
CACHE_TTL_HOURS = 24
CHARS_PER_TOKEN = 3                # rough heuristic for Korean mixed text
CLAUDE_MODEL = "claude-sonnet-4-6"


@dataclass
class SynthesisScope:
    time_range: tuple[str, str] | None = None   # (ISO start, ISO end)
    person_filter: list[str] | None = None       # canonical stems
    project_filter: list[str] | None = None
    tag_filter: list[str] | None = None
    max_sources: int = MAX_SOURCES_DEFAULT

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_range": list(self.time_range) if self.time_range else None,
            "person_filter": sorted(self.person_filter) if self.person_filter else None,
            "project_filter": sorted(self.project_filter) if self.project_filter else None,
            "tag_filter": sorted(self.tag_filter) if self.tag_filter else None,
            "max_sources": self.max_sources,
        }

    def cache_key(self, topic: str) -> str:
        canonical = json.dumps(
            {"topic": topic.strip().lower(), "scope": self.to_dict()},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class SourceNote:
    path: str
    title: str
    timestamp: str | None           # ISO 8601 if known
    content: str
    rrf_score: float = 0.0


@dataclass
class SynthesisResult:
    topic: str
    scope: SynthesisScope
    output_md: str
    sources: list[SourceNote]
    token_count_input: int
    token_count_output: int
    cached: bool = False


class Synthesizer:
    """Multi-note synthesis with hybrid search + Claude + cache."""

    def __init__(
        self,
        *,
        store: "StateStore",
        hybrid: "HybridSearch",
        graph: "VaultGraph | None",
        name_index: "VaultNameIndex",
        vault_root: Path,
        claude_client: Any,   # anthropic.AsyncAnthropic
    ) -> None:
        self._store = store
        self._hybrid = hybrid
        self._graph = graph
        self._name_index = name_index
        self._vault_root = vault_root
        self._claude = claude_client

    async def synthesize(
        self,
        topic: str,
        scope: SynthesisScope | None = None,
        *,
        force_refresh: bool = False,
    ) -> SynthesisResult:
        """Main entry point — 11-step pipeline."""
        scope = scope or SynthesisScope()
        cache_id = scope.cache_key(topic)

        # Step 1: cache check
        if not force_refresh:
            cached = await self._check_cache(cache_id)
            if cached:
                return cached

        # Step 2: hybrid search
        candidates = await self._hybrid_search(topic, scope)
        if not candidates:
            return self._empty_result(topic, scope)

        # Step 3: apply scope filters post-hoc
        candidates = self._apply_scope_filters(candidates, scope)

        # Step 4: graph expand (optional, 1-hop)
        if self._graph is not None:
            candidates = await self._graph_expand(candidates, max_add=5)

        # Step 5: trim to max_sources
        candidates = candidates[: scope.max_sources]

        # Step 6: load full content
        sources = await self._load_sources(candidates)
        if not sources:
            return self._empty_result(topic, scope)

        # Step 7: dispatch to single-shot or map-reduce
        total_input_chars = sum(len(s.content) for s in sources)
        estimated_tokens = total_input_chars // CHARS_PER_TOKEN
        logger.info("synthesis.dispatch", topic=topic, sources=len(sources), est_tokens=estimated_tokens)

        if estimated_tokens > TOKEN_BUDGET_INPUT:
            output_md, tok_in, tok_out = await self._map_reduce_synthesize(topic, scope, sources)
        else:
            output_md, tok_in, tok_out = await self._single_shot_synthesize(topic, scope, sources)

        # Step 8: post-process (wikilink resolve + sentence-per-line)
        output_md = self._post_process(output_md)

        # Step 9: build result
        result = SynthesisResult(
            topic=topic,
            scope=scope,
            output_md=output_md,
            sources=sources,
            token_count_input=tok_in,
            token_count_output=tok_out,
            cached=False,
        )

        # Step 10: cache
        await self._save_cache(cache_id, result)

        # Step 11: return
        return result

    async def _check_cache(self, cache_id: str) -> SynthesisResult | None:
        row = await self._store.get_synthesis_cache(cache_id)
        if not row:
            return None
        # TTL check
        created_at = row.get("created_at")
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at)
                if datetime.now() - dt > timedelta(hours=CACHE_TTL_HOURS):
                    return None
            except ValueError:
                pass
        scope_dict = json.loads(row["scope_json"])
        source_paths = json.loads(row["source_paths_json"])
        tr = scope_dict.get("time_range")
        scope = SynthesisScope(
            time_range=tuple(tr) if tr else None,
            person_filter=scope_dict.get("person_filter"),
            project_filter=scope_dict.get("project_filter"),
            tag_filter=scope_dict.get("tag_filter"),
            max_sources=scope_dict.get("max_sources", MAX_SOURCES_DEFAULT),
        )
        return SynthesisResult(
            topic=row["topic"],
            scope=scope,
            output_md=row["output_md"],
            sources=[SourceNote(path=p, title=Path(p).stem, timestamp=None, content="") for p in source_paths],
            token_count_input=row.get("token_count_input") or 0,
            token_count_output=row.get("token_count_output") or 0,
            cached=True,
        )

    async def _save_cache(self, cache_id: str, result: SynthesisResult) -> None:
        await self._store.set_synthesis_cache(
            cache_id=cache_id,
            topic=result.topic,
            scope_json=json.dumps(result.scope.to_dict(), ensure_ascii=False),
            output_md=result.output_md,
            source_paths_json=json.dumps([s.path for s in result.sources], ensure_ascii=False),
            source_count=len(result.sources),
            token_count_input=result.token_count_input,
            token_count_output=result.token_count_output,
            model=CLAUDE_MODEL,
        )

    async def _hybrid_search(self, topic: str, scope: SynthesisScope) -> list[dict[str, Any]]:
        """Call HybridSearch.search() — async, returns list[dict] with path + rrf_score."""
        try:
            results = await self._hybrid.search(topic, limit=scope.max_sources * 2)
            return results or []
        except Exception:
            logger.exception("synthesis.hybrid_search_failed")
            return []

    def _apply_scope_filters(self, candidates: list[dict[str, Any]], scope: SynthesisScope) -> list[dict[str, Any]]:
        """Post-hoc filter. Candidates must have 'path' key and optionally 'timestamp'."""
        filtered = candidates
        if scope.time_range:
            start, end = scope.time_range
            filtered = [c for c in filtered if self._in_time_range(c, start, end)]
        if scope.person_filter:
            filtered = [c for c in filtered if self._matches_any(c, scope.person_filter)]
        if scope.project_filter:
            filtered = [c for c in filtered if self._matches_any(c, scope.project_filter)]
        if scope.tag_filter:
            filtered = [c for c in filtered if self._matches_any(c, scope.tag_filter)]
        return filtered

    @staticmethod
    def _in_time_range(cand: dict[str, Any], start: str, end: str) -> bool:
        ts = cand.get("timestamp") or cand.get("created_at")
        if not ts:
            return True   # conservative — don't filter out unknowns
        try:
            return start <= ts <= end
        except Exception:
            return True

    @staticmethod
    def _matches_any(cand: dict[str, Any], needles: list[str]) -> bool:
        haystack = " ".join(str(v) for v in cand.values() if isinstance(v, str)).lower()
        return any(n.lower() in haystack for n in needles)

    async def _graph_expand(self, candidates: list[dict[str, Any]], *, max_add: int) -> list[dict[str, Any]]:
        """Add 1-hop neighbors from vault graph.

        VaultGraph.neighbors(entity, direction, depth) returns a dict with a
        'neighbors' key containing [{'name': str, 'hop': int}, ...].
        We extract the name values as neighbor identifiers.
        """
        if self._graph is None or not candidates:
            return candidates
        try:
            seen_paths = {c.get("path") for c in candidates if c.get("path")}
            added = 0
            for cand in list(candidates):
                path = cand.get("path")
                if not path:
                    continue
                # Use the file stem as the entity identifier for graph lookup
                stem = Path(path).stem
                result = self._graph.neighbors(stem, direction="outgoing", depth=1)
                neighbor_entries = result.get("neighbors", []) if isinstance(result, dict) else []
                for entry in neighbor_entries[:4]:
                    neighbor_name = entry.get("name") if isinstance(entry, dict) else str(entry)
                    if not neighbor_name or neighbor_name in seen_paths:
                        continue
                    candidates.append({"path": neighbor_name, "rrf_score": 0.0, "source": "graph_expand"})
                    seen_paths.add(neighbor_name)
                    added += 1
                    if added >= max_add:
                        return candidates
            return candidates
        except Exception:
            logger.exception("synthesis.graph_expand_failed")
            return candidates

    async def _load_sources(self, candidates: list[dict[str, Any]]) -> list[SourceNote]:
        """Load full markdown content for each candidate path."""
        sources: list[SourceNote] = []
        for cand in candidates:
            rel_path = cand.get("path")
            if not rel_path:
                continue
            abs_path = Path(rel_path)
            if not abs_path.is_absolute():
                abs_path = self._vault_root / rel_path
            if not abs_path.exists():
                continue
            try:
                content = abs_path.read_text(encoding="utf-8")
            except Exception:
                logger.exception("synthesis.load_failed", path=str(abs_path))
                continue
            sources.append(SourceNote(
                path=str(abs_path),
                title=abs_path.stem,
                timestamp=cand.get("timestamp") or cand.get("created_at"),
                content=content,
                rrf_score=float(cand.get("rrf_score") or cand.get("score") or 0.0),
            ))
        return sources

    async def _single_shot_synthesize(
        self,
        topic: str,
        scope: SynthesisScope,
        sources: list[SourceNote],
    ) -> tuple[str, int, int]:
        """Build prompt and call Claude once."""
        prompt = self._build_prompt(topic, scope, sources)
        response = await self._claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        output = response.content[0].text if response.content else ""
        usage = getattr(response, "usage", None)
        tok_in = getattr(usage, "input_tokens", 0) if usage else 0
        tok_out = getattr(usage, "output_tokens", 0) if usage else 0
        return output, tok_in, tok_out

    async def _map_reduce_synthesize(
        self,
        topic: str,
        scope: SynthesisScope,
        sources: list[SourceNote],
    ) -> tuple[str, int, int]:
        """Split sources into chunks, micro-summarize each, then reduce."""
        chunks = self._split_into_chunks(sources, CHUNK_SIZE_TOKENS * CHARS_PER_TOKEN)
        if len(chunks) > 20:
            logger.warning("synthesis.map_reduce_too_many_chunks", count=len(chunks))
            chunks = chunks[:20]
        micro_summaries: list[str] = []
        total_in = 0
        total_out = 0
        for i, chunk in enumerate(chunks):
            micro_prompt = self._build_micro_prompt(topic, chunk, i + 1, len(chunks))
            resp = await self._claude.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": micro_prompt}],
            )
            micro_summaries.append(resp.content[0].text if resp.content else "")
            usage = getattr(resp, "usage", None)
            total_in += getattr(usage, "input_tokens", 0) if usage else 0
            total_out += getattr(usage, "output_tokens", 0) if usage else 0

        reduce_prompt = self._build_reduce_prompt(topic, scope, micro_summaries)
        resp = await self._claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": reduce_prompt}],
        )
        final = resp.content[0].text if resp.content else ""
        usage = getattr(resp, "usage", None)
        total_in += getattr(usage, "input_tokens", 0) if usage else 0
        total_out += getattr(usage, "output_tokens", 0) if usage else 0
        return final, total_in, total_out

    @staticmethod
    def _split_into_chunks(sources: list[SourceNote], max_chars: int) -> list[list[SourceNote]]:
        chunks: list[list[SourceNote]] = []
        current: list[SourceNote] = []
        current_size = 0
        for s in sources:
            size = len(s.content)
            if current and current_size + size > max_chars:
                chunks.append(current)
                current = [s]
                current_size = size
            else:
                current.append(s)
                current_size += size
        if current:
            chunks.append(current)
        return chunks

    def _build_prompt(self, topic: str, scope: SynthesisScope, sources: list[SourceNote]) -> str:
        """Single-shot synthesis prompt. Korean-preferred, sentence-per-line rule, wikilink rule."""
        scope_desc = self._describe_scope(scope)
        source_blocks = "\n\n---\n\n".join(
            f"## {s.title}\n(경로: {s.path})\n(시점: {s.timestamp or '미상'})\n\n{s.content[:8000]}"
            for s in sources
        )
        return (
            f"다음은 '{topic}'에 대한 Obsidian vault 안의 관련 노트들이다.\n"
            f"{scope_desc}\n\n"
            f"아래 원본 노트들을 읽고, 한국어로 통합 브리프를 작성해라.\n"
            f"규칙:\n"
            f"1. 한 문장은 한 줄에 쓴다.\n"
            f"2. 고유명사 첫 등장은 [[한국어 English]] 위키링크로 표기 (순한국어는 한국어만).\n"
            f"3. 출처가 되는 노트는 본문 끝에 '참조: [[노트제목]]' 목록으로.\n"
            f"4. 사실 기반 요약만. 추측은 '(추정)' 태그.\n"
            f"5. 핵심 → 세부 → 참조 순서.\n\n"
            f"=== 원본 노트 ===\n{source_blocks}\n\n"
            f"=== 통합 브리프 ==="
        )

    def _build_micro_prompt(self, topic: str, chunk: list[SourceNote], idx: int, total: int) -> str:
        source_blocks = "\n\n---\n\n".join(
            f"## {s.title}\n{s.content[:6000]}" for s in chunk
        )
        return (
            f"'{topic}' 관련 노트 청크 {idx}/{total}. "
            f"이 청크에서 핵심 사실만 10-15줄로 추출해라. "
            f"한 사실 한 줄. 출처 노트 제목을 각 줄 끝에 (제목) 형식으로 표기.\n\n"
            f"{source_blocks}\n\n"
            f"=== 핵심 사실 ==="
        )

    def _build_reduce_prompt(self, topic: str, scope: SynthesisScope, micro_summaries: list[str]) -> str:
        joined = "\n\n---\n\n".join(f"# 청크 {i+1}\n{s}" for i, s in enumerate(micro_summaries))
        scope_desc = self._describe_scope(scope)
        return (
            f"'{topic}'에 대한 여러 청크별 핵심 사실 목록이다.\n"
            f"{scope_desc}\n\n"
            f"이들을 통합해 한국어 브리프를 작성해라.\n"
            f"규칙: 한 문장 한 줄, 고유명사 [[한국어 English]] 위키링크, 중복 제거, 시간 순 정렬, 참조 목록 끝에.\n\n"
            f"=== 청크별 사실 ===\n{joined}\n\n"
            f"=== 최종 통합 브리프 ==="
        )

    @staticmethod
    def _describe_scope(scope: SynthesisScope) -> str:
        parts = []
        if scope.time_range:
            parts.append(f"기간: {scope.time_range[0]} ~ {scope.time_range[1]}")
        if scope.person_filter:
            parts.append(f"관련 인물: {', '.join(scope.person_filter)}")
        if scope.project_filter:
            parts.append(f"프로젝트: {', '.join(scope.project_filter)}")
        if scope.tag_filter:
            parts.append(f"태그: {', '.join(scope.tag_filter)}")
        return "(" + "; ".join(parts) + ")" if parts else ""

    def _post_process(self, output_md: str) -> str:
        """Apply resolve_wikilinks and format_one_sentence_per_line."""
        try:
            from onlime.processors.name_resolver import resolve_wikilinks
            output_md = resolve_wikilinks(output_md, self._name_index)
        except Exception:
            logger.exception("synthesis.resolve_wikilinks_failed")
        try:
            from onlime.processors.summarizer import format_one_sentence_per_line
            output_md = format_one_sentence_per_line(output_md)
        except Exception:
            logger.exception("synthesis.sentence_per_line_failed")
        return output_md

    def _empty_result(self, topic: str, scope: SynthesisScope) -> SynthesisResult:
        return SynthesisResult(
            topic=topic,
            scope=scope,
            output_md=f"'{topic}' 관련 노트를 찾지 못했습니다.",
            sources=[],
            token_count_input=0,
            token_count_output=0,
            cached=False,
        )

    async def invalidate_cache_for_path(self, path: str) -> int:
        """Called by janitor when a vault file is renamed/deleted.

        Deletes cache rows whose source_paths_json contains this path.
        Returns deleted count.
        """
        try:
            cursor = await self._store.db.execute(
                "DELETE FROM synthesis_cache WHERE source_paths_json LIKE ?",
                (f"%{path}%",),
            )
            await self._store.db.commit()
            return cursor.rowcount or 0
        except Exception:
            logger.exception("synthesis.invalidate_failed", path=path)
            return 0
