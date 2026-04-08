"""Hybrid search: FTS5 keyword + LanceDB vector → RRF re-ranking."""

from __future__ import annotations

from typing import Any

import structlog

from onlime.search.fts import VaultSearch
from onlime.search.semantic import SemanticSearch

logger = structlog.get_logger()

# RRF constant (standard value from the original paper)
_RRF_K = 60


def _rrf_merge(
    fts_results: list[dict[str, Any]],
    vec_results: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion merge of two result lists.

    Each result must have a 'path' key for matching.
    Returns merged list sorted by RRF score, limited to `limit`.
    """
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}

    # FTS5 results (already ranked by BM25)
    for rank, r in enumerate(fts_results, start=1):
        path = r["path"]
        scores[path] = scores.get(path, 0.0) + 1.0 / (_RRF_K + rank)
        if path not in items:
            items[path] = r

    # Vector results (already ranked by cosine similarity)
    for rank, r in enumerate(vec_results, start=1):
        path = r["path"]
        scores[path] = scores.get(path, 0.0) + 1.0 / (_RRF_K + rank)
        if path not in items:
            items[path] = r

    # Sort by RRF score descending
    sorted_paths = sorted(scores, key=lambda p: scores[p], reverse=True)

    results = []
    for path in sorted_paths[:limit]:
        item = items[path].copy()
        item["rrf_score"] = scores[path]
        results.append(item)

    return results


class HybridSearch:
    """Combines FTS5 keyword search with LanceDB vector search via RRF."""

    def __init__(
        self,
        fts: VaultSearch,
        semantic: SemanticSearch | None = None,
    ) -> None:
        self._fts = fts
        self._semantic = semantic

    async def search(
        self,
        query: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search with graceful degradation.

        If semantic search is unavailable, falls back to FTS5 only.
        """
        # Always run FTS5 (fast, local)
        fts_results = await self._fts.search(query, limit=20, category=category)

        # Try vector search if available
        vec_results: list[dict[str, Any]] = []
        if self._semantic:
            try:
                vec_results = await self._semantic.search(query, limit=20, category=category)
            except Exception:
                logger.debug("hybrid_search.vector_failed")

        if not vec_results:
            # FTS5 only — return as-is
            logger.info("hybrid_search.fts_only", query=query, results=len(fts_results))
            return fts_results[:limit]

        if not fts_results:
            # Vector only
            logger.info("hybrid_search.vector_only", query=query, results=len(vec_results))
            return vec_results[:limit]

        # Merge via RRF
        merged = _rrf_merge(fts_results, vec_results, limit)
        logger.info(
            "hybrid_search.merged",
            query=query,
            fts=len(fts_results),
            vec=len(vec_results),
            merged=len(merged),
        )
        return merged
