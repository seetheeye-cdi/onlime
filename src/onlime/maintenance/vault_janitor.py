"""Periodic vault janitor.

Runs as a background asyncio task inside the Onlime daemon. Every interval it:

1. Sanitizes markdown filenames that contain characters Obsidian Sync
   refuses on Android/iOS (`?`, `"`, `*`, `|`, `<`, `>`, `:`, `\\`) and fixes
   stems that end in dots or spaces (which Windows/iOS reject).
2. Classifies stray `.md` files sitting at the vault root by asking Claude
   to pick one of the existing top-level folders, then moves them there.

All changes are logged via structlog. This runs without user intervention —
the user's standing instruction is "periodically, no matter what."
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask

logger = structlog.get_logger()

_FORBIDDEN = re.compile(r'[?"*|<>:\\]')
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

# Destination folders we allow the classifier to choose from (first-level
# buckets of the 3-tier vault). Keep this list tight so the LLM can't invent
# new folders.
_ROOT_BUCKETS = [
    "1.INPUT/Inbox",
    "1.INPUT/Article",
    "1.INPUT/Book",
    "1.INPUT/Class",
    "1.INPUT/Media",
    "1.INPUT/Recording",
    "1.INPUT/People",
    "1.INPUT/Quote",
    "1.INPUT/Term",
    "2.OUTPUT/Explore",
    "2.OUTPUT/People",
    "2.OUTPUT/Projects",
    "2.OUTPUT/Questions",
    "2.OUTPUT/Think",
    "2.OUTPUT/Wiki",
    "0.SYSTEM",
]


# ----- filename sanitization -----


def _sanitize_name(name: str) -> str:
    cleaned = _CTRL.sub("", name)
    cleaned = _FORBIDDEN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    stem, dot, ext = cleaned.rpartition(".")
    if not dot:
        return cleaned.rstrip(" .")
    stem = stem.rstrip(" .")
    if not stem:
        return ""
    return f"{stem}.{ext}"


def _needs_rename(name: str) -> bool:
    if _FORBIDDEN.search(name) or _CTRL.search(name):
        return True
    stem, dot, _ = name.rpartition(".")
    if dot and (stem.endswith(".") or stem.endswith(" ")):
        return True
    return False


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    i = 2
    while True:
        candidate = path.with_name(f"{stem} ({i}){ext}")
        if not candidate.exists():
            return candidate
        i += 1


def _sanitize_vault(root: Path) -> int:
    renamed = 0
    for p in root.rglob("*.md"):
        rel_parts = p.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        if not _needs_rename(p.name):
            continue
        new_name = _sanitize_name(p.name)
        if not new_name or new_name == p.name:
            continue
        new_path = _unique(p.with_name(new_name))
        try:
            p.rename(new_path)
            logger.info(
                "janitor.renamed",
                old=str(p.relative_to(root)),
                new=str(new_path.relative_to(root)),
            )
            renamed += 1
        except OSError as exc:
            logger.warning(
                "janitor.rename_failed", path=str(p.relative_to(root)), error=str(exc)
            )
    return renamed


# ----- stray root-file classification -----


@dataclass
class _Stray:
    path: Path
    content: str


def _collect_strays(root: Path) -> list[_Stray]:
    strays: list[_Stray] = []
    for p in root.glob("*.md"):
        if p.name.startswith("."):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            content = ""
        strays.append(_Stray(path=p, content=content))
    return strays


async def _classify_stray(stray: _Stray) -> str | None:
    """Ask Claude which bucket this file belongs in. Returns folder or None."""
    try:
        from onlime.llm import get_claude_client
    except Exception:
        return None

    settings = get_settings()
    buckets_str = "\n".join(f"- {b}" for b in _ROOT_BUCKETS)
    prompt = (
        "다음은 Obsidian vault 루트에 잘못 놓인 파일입니다. 아래 폴더 목록 중 "
        "가장 적절한 하나를 골라 **폴더 경로만** 답하세요. 설명 금지.\n\n"
        f"폴더 목록:\n{buckets_str}\n\n"
        f"파일명: {stray.path.name}\n"
        f"내용(앞부분):\n{stray.content[:1500] or '(빈 파일)'}\n\n"
        "답변 (폴더 경로 하나만):"
    )

    try:
        client = get_claude_client()
        resp = await client.messages.create(
            model=settings.llm.claude.model,
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = resp.content[0].text.strip()
    except Exception as exc:
        logger.warning("janitor.classify_failed", file=stray.path.name, error=str(exc))
        return None

    # Extract a known bucket from the answer (the model sometimes adds prose).
    for bucket in _ROOT_BUCKETS:
        if bucket in answer:
            return bucket
    logger.warning("janitor.classify_unknown", file=stray.path.name, answer=answer)
    return None


async def _route_strays(root: Path) -> int:
    strays = _collect_strays(root)
    if not strays:
        return 0
    moved = 0
    for stray in strays:
        bucket = await _classify_stray(stray)
        if not bucket:
            continue
        dest_dir = root / bucket
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique(dest_dir / stray.path.name)
        try:
            stray.path.rename(dest)
            logger.info(
                "janitor.routed",
                file=stray.path.name,
                bucket=bucket,
                dest=str(dest.relative_to(root)),
            )
            moved += 1
        except OSError as exc:
            logger.warning(
                "janitor.route_failed", file=stray.path.name, error=str(exc)
            )
    return moved


# ----- main loop -----


class VaultJanitor(BackgroundTask):
    """Background task that sanitizes and tidies the vault on a timer."""

    name = "vault_janitor"

    def __init__(self, interval_seconds: int = 1800, name_index: Any = None) -> None:
        super().__init__(interval_seconds)
        self._name_index = name_index  # shared VaultNameIndex for refresh

    async def run_once(self) -> None:
        settings = get_settings()
        root = settings.vault.root.expanduser()
        if not root.is_dir():
            logger.warning("janitor.vault_missing", path=str(root))
            return

        renamed = await asyncio.to_thread(_sanitize_vault, root)
        routed = await _route_strays(root)
        if renamed or routed:
            logger.info("janitor.cycle", renamed=renamed, routed=routed)
            # Refresh name index after renames so wikilink resolver sees new stems
            if self._name_index is not None:
                await asyncio.to_thread(self._name_index.rebuild, root)
                logger.info("janitor.name_index_refreshed")
