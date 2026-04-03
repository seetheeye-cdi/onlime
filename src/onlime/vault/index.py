"""Vault entity index — scans recent notes for [[wikilinks]] and builds a lookup table."""
from __future__ import annotations

import re
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Matches [[wikilink]] or [[wikilink|alias]]
_WIKILINK_RE = re.compile(r'\[\[([^\[\]|]+?)(?:\|[^\[\]]*?)?\]\]')

# Patterns to exclude from entity index
_EXCLUDE_PATTERNS = [
    re.compile(r'^\d{4}-\d{2}-\d{2}$'),           # dates like 2026-03-17
    re.compile(r'^\d{8}_'),                         # meeting notes like 20260317_...
    re.compile(r'^[^\w]'),                          # starts with emoji/icon prefix
]


class VaultIndex:
    """Builds a search-key → wikilink mapping from recent vault notes."""

    def __init__(self) -> None:
        self.entities: dict[str, str] = {}  # search_key -> "[[wikilink]]"
        self.concepts: set[str] = set()     # keys that are generic concepts (frequency-gated)

    # Hidden folders to skip during vault-wide filename scan
    _HIDDEN_DIRS = {'.obsidian', '.trash', '.git', '.DS_Store'}

    def build(
        self,
        vault_root: Path,
        daily_path: Path,
        meeting_path: Path,
        weeks: int = 4,
        entity_watchlist: list[str] | None = None,
    ) -> None:
        """Scan recent daily + meeting notes and populate the entity index."""
        cutoff = date.today() - timedelta(weeks=weeks)
        files: list[Path] = []

        # Collect recent daily notes (YYYY-MM-DD.md)
        if daily_path.is_dir():
            for f in daily_path.glob('*.md'):
                try:
                    file_date = date.fromisoformat(f.stem)
                    if file_date >= cutoff:
                        files.append(f)
                except ValueError:
                    pass

        # Collect recent meeting notes (YYYYMMDD_*.md)
        if meeting_path.is_dir():
            for f in meeting_path.glob('*.md'):
                stem = f.stem
                if len(stem) >= 8 and stem[:8].isdigit():
                    try:
                        file_date = date(
                            int(stem[:4]), int(stem[4:6]), int(stem[6:8]),
                        )
                        if file_date >= cutoff:
                            files.append(f)
                    except ValueError:
                        pass

        wikilinks = self._scan_wikilinks(files)

        for wl in wikilinks:
            is_concept = self._is_concept(wl)
            for key, link in self._parse_entity(wl):
                if key and len(key) >= 2:
                    self.entities[key] = link
                    if is_concept:
                        self.concepts.add(key)

        logger.info(f"VaultIndex built: {len(self.entities)} search keys from {len(files)} files")

        # Layer 1: Scan vault-wide filenames (lower priority than wikilinks)
        filename_count = self._scan_vault_filenames(vault_root)
        if filename_count:
            logger.info(f"Filename scan: {filename_count} new search keys")

        # Layer 4: Load watchlist entities
        if entity_watchlist:
            self._load_watchlist(entity_watchlist)
            logger.info(f"Watchlist: {len(entity_watchlist)} entities loaded")

    def _scan_vault_filenames(self, vault_root: Path) -> int:
        """Scan all .md filenames in the vault and register as entities.

        Existing wikilink-derived entities take priority (not overwritten).
        Filename-based entities are excluded from concepts (always linked).
        """
        new_count = 0
        for f in vault_root.rglob('*.md'):
            # Skip hidden directories
            if any(part in self._HIDDEN_DIRS for part in f.parts):
                continue
            target = f.stem
            for key, link in self._parse_entity(target):
                if key and len(key) >= 2 and key not in self.entities:
                    self.entities[key] = link
                    new_count += 1
        return new_count

    def _load_watchlist(self, watchlist: list[str]) -> None:
        """Register watchlist entities (not concepts, always linked)."""
        for name in watchlist:
            name = name.strip()
            if name and len(name) >= 2 and name not in self.entities:
                self.entities[name] = f"[[{name}]]"

    def add_entities(self, entities: dict[str, str]) -> None:
        """Add discovered entities to the index (e.g. from Korean-English patterns).

        Does not overwrite existing entries. Added entities are not concepts.
        """
        for key, link in entities.items():
            if key and len(key) >= 2 and key not in self.entities:
                self.entities[key] = link

    def _scan_wikilinks(self, files: list[Path]) -> set[str]:
        """Extract unique wikilink targets from a list of files."""
        links: set[str] = set()
        for f in files:
            try:
                text = f.read_text(encoding='utf-8')
                for m in _WIKILINK_RE.finditer(text):
                    links.add(m.group(1))
            except (OSError, UnicodeDecodeError):
                logger.debug(f"Skipping unreadable file: {f}")
        return links

    # Common Korean surnames — names starting with these are NOT concepts
    _KOREAN_SURNAMES = set(
        '김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽성차주우구신임라진'
    )

    def _is_concept(self, wikilink: str) -> bool:
        """Check if a wikilink is a generic concept note (frequency-gated).

        Concept notes are single-word Korean entries without underscore or
        mixed script — e.g. [[사무실]], [[담당자]], [[독서모임]].
        These are only linked if they appear 3+ times in the text.

        Person names (2-3 chars starting with a common Korean surname) are
        NOT concepts and are always linked.
        """
        target = wikilink.strip()
        if '_' in target:
            return False
        parts = target.split()
        if len(parts) != 1:
            return False
        if target.isascii():
            return False
        # Korean person names: 2-3 chars starting with a common surname
        if 2 <= len(target) <= 3 and target[0] in self._KOREAN_SURNAMES:
            return False
        return True

    def _parse_entity(self, wikilink: str) -> list[tuple[str, str]]:
        """Parse a wikilink target into (search_key, full_wikilink) pairs.

        Rules:
        - [[최동인]] → [("최동인", "[[최동인]]")]
        - [[김수민_국민의힘 당협위원장]] → [("김수민", "[[김수민_국민의힘 당협위원장]]")]
        - [[더해커톤 THEHACKATHON]] → [("더해커톤", ...), ("THEHACKATHON", ...), ("해커톤", ...)]
        - Dates, meeting-note names, emoji-prefixed links → excluded
        """
        target = wikilink.strip()

        # Check exclusion patterns
        for pat in _EXCLUDE_PATTERNS:
            if pat.search(target):
                return []

        full_link = f"[[{target}]]"
        results: list[tuple[str, str]] = []

        # Split on underscore — name part is before first underscore
        # e.g. "김수민_국민의힘 당협위원장" → "김수민" (person/project name)
        if '_' in target:
            name_part = target.split('_', 1)[0].strip()
            if name_part and len(name_part) >= 2:
                results.append((name_part, full_link))
            return results

        # Split Korean/CJK and ASCII parts (e.g. "더해커톤 THEHACKATHON")
        parts = target.split()
        has_ascii = any(p.isascii() and p.isalpha() for p in parts)
        has_korean = any(not p.isascii() for p in parts)

        if has_korean and has_ascii and len(parts) == 2:
            # Two-part mixed (Korean name + English name): decompose both
            korean_parts = [p for p in parts if not p.isascii()]
            ascii_parts = [p for p in parts if p.isascii() and p.isalpha()]

            for kp in korean_parts:
                if len(kp) >= 3:
                    results.append((kp, full_link))
                    # Strip common prefix for broader matching
                    # e.g. "더해커톤" → also match "해커톤"
                    for prefix in ('더', ):
                        if kp.startswith(prefix) and len(kp) > len(prefix) + 1:
                            results.append((kp[len(prefix):], full_link))
            for ap in ascii_parts:
                if ap.isupper() and len(ap) >= 2:
                    # ALL-CAPS acronyms: allow 2+ chars (EO, SBS, JTBC)
                    results.append((ap, full_link))
                elif len(ap) >= 4:
                    results.append((ap, full_link))

            results.append((target, full_link))
        elif has_korean and has_ascii and len(parts) >= 3:
            # Multi-part mixed phrase: only register full phrase
            results.append((target, full_link))
        elif len(parts) > 1:
            # Multi-word, same script: only register full phrase
            results.append((target, full_link))
        else:
            # ALL-CAPS ASCII: allow 2+ chars (EO, SBS, JTBC)
            if target.isascii() and target.isupper() and len(target) >= 2:
                results.append((target, full_link))
            # Simple single-word entity — require >= 3 chars to skip
            # generic concept notes (게임, 중독, 눈물, 철학, etc.)
            elif len(target) >= 3:
                results.append((target, full_link))

        return results

    def lookup(self, text: str) -> list[tuple[str, str, int, int]]:
        """Find all entity mentions in text.

        Returns list of (matched_text, wikilink, start, end) sorted by position.
        """
        if not self.entities:
            return []

        # Sort keys by length descending (longest match first)
        sorted_keys = sorted(self.entities.keys(), key=len, reverse=True)

        # Find existing [[...]] regions to protect
        protected: list[tuple[int, int]] = []
        for m in re.finditer(r'\[\[[^\[\]]*\]\]', text):
            protected.append((m.start(), m.end()))

        def _is_protected(start: int, end: int) -> bool:
            for ps, pe in protected:
                if start < pe and end > ps:
                    return True
            return False

        matches: list[tuple[str, str, int, int]] = []
        used: list[tuple[int, int]] = []  # prevent overlapping matches

        for key in sorted_keys:
            pattern = re.compile(re.escape(key))
            for m in pattern.finditer(text):
                s, e = m.start(), m.end()
                if _is_protected(s, e):
                    continue
                if any(s < ue and e > us for us, ue in used):
                    continue
                matches.append((m.group(), self.entities[key], s, e))
                used.append((s, e))

        matches.sort(key=lambda x: x[2])
        return matches
