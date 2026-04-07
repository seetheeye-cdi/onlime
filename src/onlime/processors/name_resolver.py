"""Canonical wikilink resolver — matches LLM-generated names against vault files.

Ensures one entity = one canonical wikilink across the entire vault.
Pure algorithmic matching (no LLM calls), <5ms per resolve.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Directories that contain *entity* files (not content files).
# Media is excluded — those are content *about* entities, not entity definitions.
_ENTITY_DIRS = [
    "1.INPUT/People",
    "1.INPUT/Term",
    "1.INPUT/Book",
    "2.OUTPUT/People/Active",
    "2.OUTPUT/People/Network",
    "2.OUTPUT/People/Reference",
    "2.OUTPUT/Projects",
]

# Content-file suffixes to exclude (these are *about* an entity, not the entity itself)
_CONTENT_SUFFIXES = {"_어록", "_루틴", "_통화", "_유튜브", "_인터뷰", "_리뷰"}

# Regex to split a stem into Korean and English parts
# "앤트로픽 Anthropic" → ("앤트로픽", "Anthropic")
# "일론 머스크" → ("일론 머스크", None)
# "H.P.Lovecraft" → (None, "H.P.Lovecraft")
_KO_EN_SPLIT_RE = re.compile(
    r"^([\u3131-\u3163\uac00-\ud7a3\s·,_()]+?)"  # Korean block
    r"\s+"
    r"([A-Za-z][\w\s.'\-&]+)$"  # English block
)

# Wikilink pattern: [[target]] or [[target|display]] or [[target#heading]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]+)?\]\]")

# Triple-bracket fix
_TRIPLE_BRACKET_RE = re.compile(r"\[{3,}")


@dataclass
class VaultEntity:
    """An entity file in the vault."""
    stem: str                  # filename without .md
    path: Path                 # absolute path
    category: str              # parent dir relative to vault (e.g., "1.INPUT/People")
    korean: str = ""           # Korean portion of the stem
    english: str = ""          # English portion (empty if pure Korean)
    tokens: set[str] = field(default_factory=set)  # Korean tokens for substring matching


class VaultNameIndex:
    """In-memory index of vault entity filenames for fast canonical lookup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_stem: dict[str, VaultEntity] = {}
        self._by_korean: dict[str, list[VaultEntity]] = {}
        self._by_english_lower: dict[str, list[VaultEntity]] = {}
        self._by_token: dict[str, list[VaultEntity]] = {}
        self._built = False

    @property
    def size(self) -> int:
        return len(self._by_stem)

    def build(self, vault_root: Path) -> None:
        """Scan vault entity directories and build the index."""
        vault = vault_root.expanduser()
        entities: list[VaultEntity] = []

        for rel_dir in _ENTITY_DIRS:
            dir_path = vault / rel_dir
            if not dir_path.is_dir():
                continue
            for md_file in dir_path.rglob("*.md"):
                stem = unicodedata.normalize("NFC", md_file.stem)

                # Skip content files (e.g., "일론 머스크_어록.md")
                if any(stem.endswith(suffix) for suffix in _CONTENT_SUFFIXES):
                    continue

                # For Projects dir, skip sub-pages (files with _ are sub-topics
                # like "더해커톤 THEHACKATHON_참가자.md", not entity definitions)
                if rel_dir == "2.OUTPUT/Projects" and "_" in stem:
                    continue

                entity = _parse_entity(stem, md_file, rel_dir)
                entities.append(entity)

        with self._lock:
            self._by_stem.clear()
            self._by_korean.clear()
            self._by_english_lower.clear()
            self._by_token.clear()

            for e in entities:
                self._by_stem[e.stem] = e

                if e.korean:
                    self._by_korean.setdefault(e.korean, []).append(e)
                    for tok in e.tokens:
                        if len(tok) >= 2:  # skip single-char tokens
                            self._by_token.setdefault(tok, []).append(e)

                if e.english:
                    key = e.english.lower()
                    self._by_english_lower.setdefault(key, []).append(e)

        self._built = True
        logger.info("name_index.built", entities=len(entities))

    def rebuild(self, vault_root: Path) -> None:
        """Rebuild the index (alias for build)."""
        self.build(vault_root)

    def match(self, candidate: str) -> str | None:
        """Find the canonical vault name for a candidate wikilink target.

        Returns the canonical stem if found, or None if no match.

        Match cascade (priority order):
        1. Exact stem match
        2. Korean-portion exact match
        3. English-portion exact match (case-insensitive)
        4. Token containment (candidate tokens ⊂ entity tokens or vice versa)
        """
        if not self._built:
            return None

        candidate = candidate.strip()
        if not candidate:
            return None

        with self._lock:
            # 1. Exact stem match
            if candidate in self._by_stem:
                return candidate  # already canonical

            # Parse candidate into Korean/English parts
            cand_ko, cand_en = _split_ko_en(candidate)

            # 2. Korean-portion exact match
            if cand_ko and cand_ko in self._by_korean:
                entities = self._by_korean[cand_ko]
                best = _pick_best(entities)
                if best:
                    return best.stem

            # 3. English-portion exact match (case-insensitive)
            if cand_en:
                key = cand_en.lower()
                if key in self._by_english_lower:
                    entities = self._by_english_lower[key]
                    best = _pick_best(entities)
                    if best:
                        return best.stem

            # 4. Token containment — candidate is a subset of an entity
            cand_tokens = _tokenize_korean(cand_ko or candidate)
            if cand_tokens:
                best_score = 0.0
                best_entity: VaultEntity | None = None
                checked: set[str] = set()
                for tok in cand_tokens:
                    for entity in self._by_token.get(tok, []):
                        if entity.stem in checked:
                            continue
                        checked.add(entity.stem)
                        overlap = cand_tokens & entity.tokens
                        if not overlap:
                            continue
                        # Subset match: all candidate tokens exist in entity
                        if cand_tokens <= entity.tokens:
                            # Score: prefer entities where candidate covers more
                            score = 2.0 + len(overlap) / len(entity.tokens)
                        # Superset match: all entity tokens exist in candidate
                        elif entity.tokens <= cand_tokens:
                            score = 1.5 + len(overlap) / len(cand_tokens)
                        else:
                            # Partial overlap — require >40% Jaccard
                            union = len(cand_tokens | entity.tokens)
                            jaccard = len(overlap) / union
                            if jaccard <= 0.4:
                                continue
                            score = jaccard
                        if score > best_score:
                            best_score = score
                            best_entity = entity

                if best_entity:
                    return best_entity.stem

        return None  # no match found


def resolve_wikilinks(text: str, index: VaultNameIndex) -> str:
    """Replace wikilink targets with canonical vault names.

    Also fixes triple-bracket [[[  → [[ as a safety net.
    """
    if not text:
        return text

    # Fix triple brackets first
    text = _TRIPLE_BRACKET_RE.sub("[[", text)

    seen: dict[str, str] = {}

    def _replace(m: re.Match) -> str:
        original = m.group(1).strip()
        if original in seen:
            resolved = seen[original]
        else:
            resolved = index.match(original) or original
            seen[original] = resolved
        if resolved == original:
            return m.group(0)
        # Preserve the full match structure (|alias, #heading)
        full = m.group(0)
        old_target = m.group(1)
        return full.replace(f"[[{old_target}", f"[[{resolved}", 1)

    return _WIKILINK_RE.sub(_replace, text)


def resolve_keywords(keywords: list[str], index: VaultNameIndex) -> list[str]:
    """Resolve keyword list to canonical vault names, deduplicating."""
    resolved: list[str] = []
    seen: set[str] = set()

    for kw in keywords:
        canonical = index.match(kw) or kw
        # Dedup by canonical name (case-insensitive for safety)
        dedup_key = canonical.lower()
        if dedup_key not in seen:
            resolved.append(canonical)
            seen.add(dedup_key)

    return resolved


# --- Internal helpers ---


def _parse_entity(stem: str, path: Path, category: str) -> VaultEntity:
    """Parse a vault filename into a VaultEntity.

    For People files with tag format ("이름_태그1, 태그2"), only the name
    part is used for Korean/token matching to avoid false positives
    (e.g., "토스" matching a person tagged with 토스).
    """
    # For People entities, extract just the name portion before tags
    is_people = "People" in category
    match_stem = stem
    if is_people and "_" in stem:
        # "이태양_더해커톤, 토스 공동창업, BASS Ventures" → "이태양"
        match_stem = stem.split("_", 1)[0].strip()

    korean, english = _split_ko_en(match_stem)
    tokens = _tokenize_korean(korean or match_stem)

    return VaultEntity(
        stem=stem,
        path=path,
        category=category,
        korean=korean or match_stem,
        english=english or "",
        tokens=tokens,
    )


def _split_ko_en(text: str) -> tuple[str, str]:
    """Split "한국어 English" into (Korean, English) parts.

    Returns (text, "") if pure Korean or can't split.
    Returns ("", text) if pure English.
    """
    text = text.strip()
    m = _KO_EN_SPLIT_RE.match(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Check if pure English
    if text and all(not ('\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u3163') for c in text if c.strip()):
        return "", text

    # Pure Korean or mixed — return as Korean
    return text, ""


def _tokenize_korean(text: str) -> set[str]:
    """Tokenize Korean text into meaningful chunks.

    Splits on spaces, punctuation, and common delimiters.
    Filters out tokens shorter than 2 characters.
    """
    if not text:
        return set()
    # Split on whitespace and common delimiters
    parts = re.split(r"[\s·,_()（）\-]+", text)
    return {p for p in parts if len(p) >= 2}


def _pick_best(entities: list[VaultEntity]) -> VaultEntity | None:
    """Pick the best entity from a list of candidates.

    Priority: People > Term > others, then shorter stems preferred.
    """
    if not entities:
        return None
    if len(entities) == 1:
        return entities[0]

    # Priority order for categories
    _CAT_PRIORITY = {
        "1.INPUT/People": 0,
        "2.OUTPUT/People/Active": 1,
        "2.OUTPUT/People/Network": 2,
        "2.OUTPUT/People/Reference": 3,
        "1.INPUT/Term": 4,
        "2.OUTPUT/Projects": 5,
        "1.INPUT/Book": 6,
    }

    return min(
        entities,
        key=lambda e: (_CAT_PRIORITY.get(e.category, 99), len(e.stem)),
    )
