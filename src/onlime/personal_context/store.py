"""YAML-backed personal context store for LLM prompt injection."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


@dataclass
class Fact:
    key: str
    value: str
    category: str            # 'relationship'|'project'|'ontology'|'alias'|'preference'
    priority: int = 50       # 0-100
    visibility: str = "public"  # 'public'|'internal'
    notes: str | None = None


class PersonalContextStore:
    """Loads facts from ~/.onlime/personal_context.yaml with mtime-based hot reload."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._facts: list[Fact] = []
        self._aliases: dict[str, str] = {}
        self._mtime: float = 0.0

    def load(self) -> None:
        """Read YAML from disk. Falls back to last known state on YAMLError."""
        if not self._path.exists():
            logger.info("personal_context.file_missing", path=str(self._path))
            self._facts = []
            self._aliases = {}
            self._mtime = 0.0
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw) or {}
        except yaml.YAMLError as exc:
            logger.error("personal_context.yaml_error", path=str(self._path), error=str(exc))
            return  # retain previous state

        facts: list[Fact] = []
        for item in data.get("facts", []) or []:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            category = item.get("category")
            if not key or not value or not category:
                logger.warning("personal_context.invalid_fact", item=item)
                continue
            facts.append(Fact(
                key=str(key),
                value=str(value),
                category=str(category),
                priority=int(item.get("priority", 50)),
                visibility=str(item.get("visibility", "public")),
                notes=str(item["notes"]) if item.get("notes") is not None else None,
            ))

        aliases: dict[str, str] = {}
        raw_aliases = data.get("aliases") or {}
        if isinstance(raw_aliases, dict):
            for k, v in raw_aliases.items():
                aliases[str(k)] = str(v)

        self._facts = facts
        self._aliases = aliases
        self._mtime = self._path.stat().st_mtime
        logger.info("personal_context.loaded", facts=len(facts), aliases=len(aliases))

    def reload_if_changed(self) -> bool:
        """Re-read file if mtime has advanced. Returns True if reloaded."""
        if not self._path.exists():
            if self._facts or self._aliases:
                self._facts = []
                self._aliases = {}
                self._mtime = 0.0
                return True
            return False
        try:
            current_mtime = self._path.stat().st_mtime
        except OSError:
            return False
        if current_mtime > self._mtime:
            self.load()
            return True
        return False

    def add_fact(self, fact: Fact) -> None:
        """Append a fact and persist to YAML."""
        self._facts = [f for f in self._facts if f.key != fact.key]
        self._facts.append(fact)
        self._persist()

    def remove_fact(self, key: str) -> bool:
        """Remove by key. Returns True if removed."""
        before = len(self._facts)
        self._facts = [f for f in self._facts if f.key != key]
        if len(self._facts) < before:
            self._persist()
            return True
        return False

    def list_facts(
        self,
        category: str | None = None,
        include_internal: bool = True,
    ) -> list[Fact]:
        """Return facts filtered by category. include_internal=False excludes visibility='internal'."""
        result = self._facts
        if category is not None:
            result = [f for f in result if f.category == category]
        if not include_internal:
            result = [f for f in result if f.visibility != "internal"]
        return result

    def resolve_alias(self, name: str) -> str:
        """Return canonical name or input unchanged."""
        return self._aliases.get(name, name)

    def build_system_suffix(
        self,
        max_tokens: int,
        categories: list[str] | None = None,
    ) -> str:
        """Build a markdown block for LLM system prompt injection.

        Filters by categories if provided, sorts by priority DESC, truncates to max_tokens.
        Returns empty string if no facts.
        Token heuristic: 1 token ≈ 3 chars for Korean mixed text.
        """
        facts = self._facts
        if categories is not None:
            facts = [f for f in facts if f.category in categories]
        if not facts:
            return ""

        facts = sorted(facts, key=lambda f: f.priority, reverse=True)

        max_chars = max_tokens * 3
        header = "\n\n[개인 맥락]\n"
        lines: list[str] = []
        used = len(header)

        for fact in facts:
            line = f"- {fact.value}\n"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)

        if not lines:
            return ""

        return header + "".join(lines)

    def _persist(self) -> None:
        """Write current state back to YAML atomically (tmp + rename)."""
        data: dict[str, Any] = {
            "version": 1,
            "facts": [
                {
                    "key": f.key,
                    "value": f.value,
                    "category": f.category,
                    "priority": f.priority,
                    "visibility": f.visibility,
                    **({"notes": f.notes} if f.notes is not None else {}),
                }
                for f in self._facts
            ],
            "aliases": dict(self._aliases),
        }
        tmp = self._path.with_suffix(".yaml.tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
        tmp.replace(self._path)
        if self._path.exists():
            self._mtime = self._path.stat().st_mtime
