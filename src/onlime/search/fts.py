"""Full-text search over the Obsidian vault using SQLite FTS5."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger()

_FTS_CREATE = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5("
    "path, title, content, category, updated_at UNINDEXED, "
    "tokenize='unicode61'"
    ")"
)

# Strip YAML frontmatter block
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown content."""
    return _FRONTMATTER_RE.sub("", text, count=1)


def _sanitize_fts_query(query: str) -> str:
    """Sanitize user query for FTS5 syntax.

    Wraps each word in double quotes to prevent FTS5 syntax errors
    from special characters. Joins with space (implicit AND).
    """
    words = query.strip().split()
    if not words:
        return '""'
    return " ".join(f'"{w}"' for w in words)


class VaultSearch:
    """FTS5-based vault search engine."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def ensure_schema(self) -> None:
        """Create the FTS5 virtual table if it doesn't exist."""
        await self._db.execute(_FTS_CREATE)
        await self._db.commit()
        logger.info("vault_search.schema_ready")

    async def index_file(self, path: Path, vault_root: Path) -> None:
        """Index a single markdown file into FTS5."""
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        rel_path = str(path.relative_to(vault_root))
        title = path.stem
        body = _strip_frontmatter(content)
        category = _extract_category(rel_path)
        updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()

        # Upsert: DELETE + INSERT (FTS5 doesn't support UPDATE)
        await self._db.execute(
            "DELETE FROM vault_fts WHERE path = ?", (rel_path,)
        )
        await self._db.execute(
            "INSERT INTO vault_fts (path, title, content, category, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (rel_path, title, body, category, updated_at),
        )

    async def index_vault(self, vault_root: Path) -> int:
        """Full reindex of the vault. Returns number of files indexed."""
        count = 0
        for md_file in vault_root.rglob("*.md"):
            # Skip system/hidden files
            if any(part.startswith(".") for part in md_file.parts):
                continue
            await self.index_file(md_file, vault_root)
            count += 1

        await self._db.commit()
        logger.info("vault_search.indexed", files=count)
        return count

    async def search(
        self,
        query: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search the vault. Returns list of {path, title, snippet, rank}."""
        safe_query = _sanitize_fts_query(query)

        if category:
            sql = (
                "SELECT path, title, "
                "snippet(vault_fts, 2, '→', '←', '...', 40) AS snippet, "
                "rank "
                "FROM vault_fts "
                "WHERE vault_fts MATCH ? AND category = ? "
                "ORDER BY rank "
                "LIMIT ?"
            )
            cursor = await self._db.execute(sql, (safe_query, category, limit))
        else:
            sql = (
                "SELECT path, title, "
                "snippet(vault_fts, 2, '→', '←', '...', 40) AS snippet, "
                "rank "
                "FROM vault_fts "
                "WHERE vault_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ?"
            )
            cursor = await self._db.execute(sql, (safe_query, limit))

        rows = await cursor.fetchall()
        results = [
            {
                "path": row[0],
                "title": row[1],
                "snippet": row[2],
                "rank": row[3],
            }
            for row in rows
        ]
        logger.info("vault_search.query", query=query, results=len(results))
        return results

    async def get_indexed_count(self) -> int:
        """Return the number of indexed documents."""
        cursor = await self._db.execute("SELECT COUNT(*) FROM vault_fts")
        row = await cursor.fetchone()
        return row[0] if row else 0


def _extract_category(rel_path: str) -> str:
    """Extract top-level category from relative vault path.

    '1.INPUT/Media/foo.md' → 'Media'
    '2.OUTPUT/Daily/2026-04-01.md' → 'Daily'
    """
    parts = rel_path.split("/")
    if len(parts) >= 2:
        return parts[1] if parts[0] in ("0.SYSTEM", "1.INPUT", "2.OUTPUT") else parts[0]
    return ""
