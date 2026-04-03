"""Auto-link entity mentions in text with [[wikilinks]]."""
from __future__ import annotations

import re
import logging

from onlime.vault.index import VaultIndex

logger = logging.getLogger(__name__)

# Matches 한국어(English) patterns: Korean 3+ chars, English starts uppercase (proper nouns)
# e.g. 캔디드(Candid), 바이브코딩(Vibe Coding)
# Excludes: 관리(CRM), 집중(Concentrate) — 2-char Korean is almost always generic terms
_KO_EN_RE = re.compile(r'([가-힣]{3,})\(([A-Z][A-Za-z .&\-]*[A-Za-z])\)')


def discover_korean_english(text: str) -> dict[str, str]:
    """Discover 한국어(English) patterns in text and return entity mappings.

    Only registers entities where the English part is 4+ chars (excludes
    short acronyms like OS, IP, PO, UBI which are generic translations).

    Returns dict of search_key -> "[[wikilink]]" for discovered entities.
    e.g. {"캔디드 Candid": "[[캔디드 Candid]]", "캔디드": "[[캔디드 Candid]]"}
    """
    entities: dict[str, str] = {}
    for m in _KO_EN_RE.finditer(text):
        korean = m.group(1)
        english = m.group(2).strip()
        # Skip short English acronyms (OS, IP, PO, UBI, COI, etc.)
        if len(english) < 4:
            continue
        combined = f"{korean} {english}"
        link = f"[[{combined}]]"
        entities[combined] = link
        if len(korean) >= 3:
            entities.setdefault(korean, link)
    return entities


def _replace_korean_english_patterns(text: str, index: VaultIndex) -> str:
    """Pre-process text to replace 한국어(English) with [[한국어 English]] wikilinks.

    Handles the atomic replacement so auto_link() doesn't partially match.
    Skips patterns already inside [[...]].
    """
    # Find protected [[...]] regions
    protected: list[tuple[int, int]] = []
    for m in re.finditer(r'\[\[[^\[\]]*\]\]', text):
        protected.append((m.start(), m.end()))

    def _is_protected(start: int, end: int) -> bool:
        for ps, pe in protected:
            if start < pe and end > ps:
                return True
        return False

    replacements: list[tuple[int, int, str]] = []
    for m in _KO_EN_RE.finditer(text):
        s, e = m.start(), m.end()
        if _is_protected(s, e):
            continue
        korean = m.group(1)
        english = m.group(2).strip()
        combined = f"{korean} {english}"
        replacements.append((s, e, f"[[{combined}]]"))

    if not replacements:
        return text

    # Apply from end to preserve offsets
    replacements.sort(key=lambda x: x[0], reverse=True)
    result = text
    for start, end, repl in replacements:
        result = result[:start] + repl + result[end:]

    return result


def auto_link(text: str, index: VaultIndex) -> str:
    """Replace entity mentions in text with [[wikilinks]].

    - Protects existing [[...]] regions from double-linking
    - Longest match first to avoid partial replacements
    - Uses [[target|display]] when the search key differs from the wikilink target
    - Concept entities (generic nouns) only linked if they appear 3+ times
    """
    if not text or not index.entities:
        return text

    # 0. Pre-process: replace 한국어(English) patterns atomically
    text = _replace_korean_english_patterns(text, index)

    # 1. Find and protect existing [[...]] regions
    protected: list[tuple[int, int]] = []
    for m in re.finditer(r'\[\[[^\[\]]*\]\]', text):
        protected.append((m.start(), m.end()))

    def _is_protected(start: int, end: int) -> bool:
        for ps, pe in protected:
            if start < pe and end > ps:
                return True
        return False

    # 2. Pre-count concept entity occurrences for frequency gating
    _MIN_CONCEPT_FREQ = 3
    concept_skip: set[str] = set()
    for key in index.concepts:
        count = len(re.findall(re.escape(key), text))
        if count < _MIN_CONCEPT_FREQ:
            concept_skip.add(key)

    # 3. Sort search keys by length descending (longest match first)
    sorted_keys = sorted(index.entities.keys(), key=len, reverse=True)

    # 4. Collect all replacements (don't modify text in-place during search)
    replacements: list[tuple[int, int, str]] = []
    used: list[tuple[int, int]] = []

    for key in sorted_keys:
        if key in concept_skip:
            continue

        pattern = re.compile(re.escape(key))
        for m in pattern.finditer(text):
            s, e = m.start(), m.end()

            # Skip if inside protected region
            if _is_protected(s, e):
                continue

            # Skip if overlapping with an already-planned replacement
            if any(s < ue and e > us for us, ue in used):
                continue

            wikilink = index.entities[key]
            matched_text = m.group()

            # Extract the target from [[target]]
            target = wikilink[2:-2]  # strip [[ and ]]

            # If matched text differs from target, use [[target|matched_text]]
            if matched_text != target:
                replacement = f"[[{target}|{matched_text}]]"
            else:
                replacement = wikilink

            replacements.append((s, e, replacement))
            used.append((s, e))

    if not replacements:
        return text

    # 4. Apply replacements from end to start (preserve offsets)
    replacements.sort(key=lambda x: x[0], reverse=True)
    result = text
    for start, end, repl in replacements:
        result = result[:start] + repl + result[end:]

    return result
