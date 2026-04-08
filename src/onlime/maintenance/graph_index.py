"""Background task: periodic wikilink graph indexing of the Obsidian vault."""

from __future__ import annotations

import time
from pathlib import Path

import structlog

from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask
from onlime.search.graph import VaultGraph

logger = structlog.get_logger()


class GraphIndexTask(BackgroundTask):
    """Periodically re-index wikilink edges into SQLite + NetworkX."""

    name = "graph_index"

    def __init__(self, interval_seconds: int, graph: VaultGraph) -> None:
        super().__init__(interval_seconds)
        self._graph = graph
        self._first_run = True
        self._last_indexed_at: float = 0.0

    async def run_once(self) -> None:
        settings = get_settings()
        vault_root = settings.vault.root.expanduser()

        if self._first_run:
            # Load persisted edges, then full scan
            await self._graph.load_from_db()
            nodes, edges = await self._graph.index_vault(vault_root)
            self._first_run = False
            self._last_indexed_at = time.time()
            logger.info("graph_index.full_scan", nodes=nodes, edges=edges)
        else:
            count = await self._incremental_index(vault_root)
            logger.info("graph_index.incremental", files=count)

    async def _incremental_index(self, vault_root: Path) -> int:
        """Index only files modified since last run."""
        count = 0
        cutoff = self._last_indexed_at
        self._last_indexed_at = time.time()

        for md_file in vault_root.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue
            try:
                if md_file.stat().st_mtime > cutoff:
                    await self._graph.index_file(md_file, vault_root)
                    count += 1
            except OSError:
                continue

        if count:
            await self._graph._db.commit()
        return count
