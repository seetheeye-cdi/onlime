"""Wikilink-based knowledge graph over the Obsidian vault.

SQLite stores edges persistently; NetworkX provides in-memory graph queries.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import networkx as nx
import structlog

from onlime.processors.name_resolver import VaultNameIndex, _WIKILINK_RE

logger = structlog.get_logger()

# Strip YAML frontmatter
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)

_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS vault_edges (
        source_path TEXT NOT NULL,
        target      TEXT NOT NULL,
        target_path TEXT,
        updated_at  TEXT NOT NULL,
        PRIMARY KEY (source_path, target)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vault_edges_target ON vault_edges (target)",
    "CREATE INDEX IF NOT EXISTS idx_vault_edges_target_path ON vault_edges (target_path)",
]


class VaultGraph:
    """SQLite-persisted + NetworkX in-memory knowledge graph."""

    def __init__(self, db: aiosqlite.Connection, name_index: VaultNameIndex) -> None:
        self._db = db
        self._name_index = name_index
        self._g: nx.DiGraph = nx.DiGraph()

    # --- Schema & Loading ---

    async def ensure_schema(self) -> None:
        for sql in _SCHEMA_SQL:
            await self._db.execute(sql)
        await self._db.commit()
        logger.info("graph.schema_ready")

    async def load_from_db(self) -> None:
        """Rebuild NetworkX graph from SQLite (for daemon restart)."""
        self._g.clear()
        cursor = await self._db.execute(
            "SELECT source_path, target, target_path FROM vault_edges"
        )
        count = 0
        async for row in cursor:
            source_path, target, target_path = row
            source_stem = Path(source_path).stem
            source_stem = unicodedata.normalize("NFC", source_stem)
            target = unicodedata.normalize("NFC", target)
            self._g.add_node(source_stem, path=source_path)
            self._g.add_node(target, path=target_path or "")
            self._g.add_edge(source_stem, target)
            count += 1
        logger.info("graph.loaded", nodes=self._g.number_of_nodes(), edges=count)

    # --- Indexing ---

    async def index_file(self, md_file: Path, vault_root: Path) -> int:
        """Extract wikilinks from one file, update DB + graph. Returns edge count."""
        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return 0

        rel_path = str(md_file.relative_to(vault_root))
        body = _FRONTMATTER_RE.sub("", content, count=1)
        targets = _extract_wikilinks(body)

        if not targets:
            # Remove old edges for this file
            await self._db.execute(
                "DELETE FROM vault_edges WHERE source_path = ?", (rel_path,)
            )
            source_stem = unicodedata.normalize("NFC", md_file.stem)
            for _, _, data in list(self._g.out_edges(source_stem, data=True)):
                pass
            # Remove outgoing edges from graph
            if source_stem in self._g:
                out_targets = list(self._g.successors(source_stem))
                for t in out_targets:
                    self._g.remove_edge(source_stem, t)
            return 0

        now = datetime.now().isoformat()
        source_stem = unicodedata.normalize("NFC", md_file.stem)

        # Clear old edges for this file
        await self._db.execute(
            "DELETE FROM vault_edges WHERE source_path = ?", (rel_path,)
        )
        if source_stem in self._g:
            old_targets = list(self._g.successors(source_stem))
            for t in old_targets:
                self._g.remove_edge(source_stem, t)

        # Insert new edges
        self._g.add_node(source_stem, path=rel_path)
        for target in targets:
            # Resolve target to canonical path via VaultNameIndex
            canonical = self._name_index.match(target)
            if canonical and canonical in self._name_index._by_stem:
                entity = self._name_index._by_stem[canonical]
                target_path = str(entity.path.relative_to(vault_root)) if entity.path.is_relative_to(vault_root) else None
                display_name = canonical
            else:
                target_path = None
                display_name = target

            await self._db.execute(
                "INSERT OR REPLACE INTO vault_edges (source_path, target, target_path, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (rel_path, display_name, target_path, now),
            )
            self._g.add_node(display_name, path=target_path or "")
            self._g.add_edge(source_stem, display_name)

        return len(targets)

    async def index_vault(self, vault_root: Path) -> tuple[int, int]:
        """Full vault scan. Returns (node_count, edge_count)."""
        self._g.clear()
        await self._db.execute("DELETE FROM vault_edges")

        total_edges = 0
        for md_file in vault_root.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue
            edges = await self.index_file(md_file, vault_root)
            total_edges += edges

        await self._db.commit()
        nodes = self._g.number_of_nodes()
        edges = self._g.number_of_edges()
        logger.info("graph.full_scan", nodes=nodes, edges=edges)
        return nodes, edges

    # --- Query Methods ---

    def neighbors(
        self,
        entity: str,
        direction: str = "both",
        depth: int = 1,
    ) -> dict[str, Any]:
        """Find neighbors of an entity up to N hops."""
        node = self._resolve_node(entity)
        if node is None:
            return {"error": f"'{entity}'을(를) 그래프에서 찾을 수 없습니다."}

        depth = max(1, min(depth, 3))

        if direction == "outgoing":
            result = _bfs(self._g, node, depth, reverse=False)
        elif direction == "incoming":
            result = _bfs(self._g, node, depth, reverse=True)
        else:
            out = _bfs(self._g, node, depth, reverse=False)
            inc = _bfs(self._g, node, depth, reverse=True)
            # Merge, removing duplicates
            result = {}
            for k, v in out.items():
                result[k] = v
            for k, v in inc.items():
                if k not in result:
                    result[k] = v

        return {
            "entity": node,
            "direction": direction,
            "depth": depth,
            "neighbors": [
                {"name": name, "hop": hop} for name, hop in result.items()
            ],
            "count": len(result),
        }

    def shortest_path(self, source: str, target: str) -> dict[str, Any]:
        """Find shortest path between two entities."""
        src = self._resolve_node(source)
        tgt = self._resolve_node(target)

        if src is None:
            return {"error": f"'{source}'을(를) 그래프에서 찾을 수 없습니다."}
        if tgt is None:
            return {"error": f"'{target}'을(를) 그래프에서 찾을 수 없습니다."}

        undirected = self._g.to_undirected()
        try:
            path = nx.shortest_path(undirected, src, tgt)
            return {
                "source": src,
                "target": tgt,
                "path": path,
                "length": len(path) - 1,
            }
        except nx.NetworkXNoPath:
            return {
                "source": src,
                "target": tgt,
                "path": [],
                "length": -1,
                "message": f"'{src}'와 '{tgt}' 사이에 연결 경로가 없습니다.",
            }

    def node_stats(self, entity: str) -> dict[str, Any]:
        """Get in/out degree for a node."""
        node = self._resolve_node(entity)
        if node is None:
            return {"error": f"'{entity}'을(를) 그래프에서 찾을 수 없습니다."}

        return {
            "entity": node,
            "in_degree": self._g.in_degree(node),
            "out_degree": self._g.out_degree(node),
            "incoming": sorted(self._g.predecessors(node))[:20],
            "outgoing": sorted(self._g.successors(node))[:20],
        }

    def top_nodes(
        self,
        metric: str = "in_degree",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Top nodes by a given metric."""
        limit = max(1, min(limit, 30))

        if metric == "pagerank":
            scores = nx.pagerank(self._g)
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
            return {
                "metric": metric,
                "nodes": [{"name": n, "score": round(s, 6)} for n, s in ranked],
            }
        elif metric == "out_degree":
            ranked = sorted(self._g.nodes(), key=lambda n: self._g.out_degree(n), reverse=True)[:limit]
            return {
                "metric": metric,
                "nodes": [{"name": n, "score": self._g.out_degree(n)} for n in ranked],
            }
        else:
            # Default: in_degree
            ranked = sorted(self._g.nodes(), key=lambda n: self._g.in_degree(n), reverse=True)[:limit]
            return {
                "metric": "in_degree",
                "nodes": [{"name": n, "score": self._g.in_degree(n)} for n in ranked],
            }

    def summary(self) -> dict[str, Any]:
        """Overall graph summary."""
        return {
            "nodes": self._g.number_of_nodes(),
            "edges": self._g.number_of_edges(),
        }

    # --- Internal ---

    def _resolve_node(self, identifier: str) -> str | None:
        """Fuzzy-match an identifier to an existing graph node."""
        identifier = unicodedata.normalize("NFC", identifier.strip())
        if not identifier:
            return None

        # Exact match
        if identifier in self._g:
            return identifier

        # Try VaultNameIndex canonical match
        canonical = self._name_index.match(identifier)
        if canonical and canonical in self._g:
            return canonical

        # Case-insensitive scan (last resort, only over existing nodes)
        lower = identifier.lower()
        for node in self._g.nodes():
            if node.lower() == lower:
                return node

        return None


def _extract_wikilinks(text: str) -> list[str]:
    """Extract unique wikilink targets from markdown body."""
    seen: set[str] = set()
    result: list[str] = []
    for m in _WIKILINK_RE.finditer(text):
        target = unicodedata.normalize("NFC", m.group(1).strip())
        if target and target not in seen:
            seen.add(target)
            result.append(target)
    return result


def _bfs(g: nx.DiGraph, start: str, depth: int, reverse: bool) -> dict[str, int]:
    """BFS from start up to depth hops. Returns {node: hop_distance}."""
    visited: dict[str, int] = {}
    queue: list[tuple[str, int]] = [(start, 0)]
    while queue:
        node, d = queue.pop(0)
        if d > depth:
            break
        if node == start and d > 0:
            continue
        if node in visited:
            continue
        if node != start:
            visited[node] = d
        if d < depth:
            nexts = g.predecessors(node) if reverse else g.successors(node)
            for nb in nexts:
                if nb not in visited:
                    queue.append((nb, d + 1))
    return visited
