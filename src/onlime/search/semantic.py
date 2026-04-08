"""Semantic vector search over the Obsidian vault using LanceDB + Ollama embeddings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import lancedb
import pyarrow as pa
import structlog

from onlime.config import get_settings

logger = structlog.get_logger()

# Strip YAML frontmatter block
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)

_SCHEMA = pa.schema([
    pa.field("path", pa.utf8()),
    pa.field("title", pa.utf8()),
    pa.field("category", pa.utf8()),
    pa.field("vector", pa.list_(pa.float32(), 768)),
])


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _extract_category(rel_path: str) -> str:
    parts = rel_path.split("/")
    if len(parts) >= 2:
        return parts[1] if parts[0] in ("0.SYSTEM", "1.INPUT", "2.OUTPUT") else parts[0]
    return ""


class SemanticSearch:
    """LanceDB-based semantic search with Ollama embeddings."""

    def __init__(self) -> None:
        settings = get_settings()
        db_path = Path(settings.search.db_path).expanduser()
        db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(db_path))
        self._model = settings.search.embedding_model
        self._ollama_url = settings.search.ollama_url
        self._table: lancedb.table.Table | None = None
        self._available: bool | None = None

    def _get_table(self) -> lancedb.table.Table:
        if self._table is None:
            try:
                self._table = self._db.open_table("vault_vectors")
            except Exception:
                self._table = self._db.create_table("vault_vectors", schema=_SCHEMA)
        return self._table

    async def check_available(self) -> bool:
        """Check if Ollama is running and the embedding model is available."""
        if self._available is not None:
            return self._available
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._ollama_url}/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    # Match with or without ":latest" tag
                    self._available = any(
                        m == self._model or m.startswith(f"{self._model}:")
                        for m in models
                    )
                    if not self._available:
                        logger.warning("semantic_search.model_not_found", model=self._model, available=models)
                else:
                    self._available = False
        except Exception:
            self._available = False
            logger.info("semantic_search.ollama_unavailable")
        return self._available

    async def embed_text(self, text: str) -> list[float] | None:
        """Get embedding vector from Ollama."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._ollama_url}/api/embed",
                    json={"model": self._model, "input": text},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings")
                    if embeddings and len(embeddings) > 0:
                        return embeddings[0]
                return None
        except Exception:
            logger.debug("semantic_search.embed_failed")
            return None

    async def index_file(self, path: Path, vault_root: Path) -> bool:
        """Index a single markdown file into LanceDB. Returns True if indexed."""
        if not await self.check_available():
            return False

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False

        rel_path = str(path.relative_to(vault_root))
        title = path.stem
        body = _strip_frontmatter(content)

        # Truncate to ~8000 chars (~2000 tokens) for embedding
        # Front of document has highest information density
        text_for_embed = f"{title}\n\n{body}"[:8000]

        vector = await self.embed_text(text_for_embed)
        if vector is None:
            return False

        category = _extract_category(rel_path)
        table = self._get_table()

        # Upsert: delete existing then add
        try:
            table.delete(f'path = "{rel_path}"')
        except Exception:
            pass

        table.add([{
            "path": rel_path,
            "title": title,
            "category": category,
            "vector": vector,
        }])
        return True

    async def index_vault(self, vault_root: Path) -> int:
        """Full reindex of the vault. Returns number of files indexed."""
        if not await self.check_available():
            logger.info("semantic_search.skip_index", reason="ollama_unavailable")
            return 0

        count = 0
        for md_file in vault_root.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue
            if await self.index_file(md_file, vault_root):
                count += 1
                if count % 100 == 0:
                    logger.info("semantic_search.indexing_progress", count=count)

        logger.info("semantic_search.indexed", files=count)
        return count

    async def search(
        self,
        query: str,
        limit: int = 20,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search by vector similarity. Returns list of {path, title, category, score}."""
        if not await self.check_available():
            return []

        vector = await self.embed_text(query)
        if vector is None:
            return []

        table = self._get_table()
        try:
            q = table.search(vector).limit(limit)
            if category:
                q = q.where(f'category = "{category}"')
            raw = q.to_list()
        except Exception:
            logger.debug("semantic_search.search_failed")
            return []

        results = []
        for row in raw:
            results.append({
                "path": row["path"],
                "title": row["title"],
                "category": row.get("category", ""),
                "score": 1.0 - row.get("_distance", 0.0),  # cosine similarity
            })
        return results
