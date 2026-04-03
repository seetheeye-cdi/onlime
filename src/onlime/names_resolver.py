"""Auto-resolve KakaoTalk nicknames to real names.

Data sources (loaded once, cached):
  1. contacts.csv — Google Contacts export
  2. Obsidian People folder — note filenames
  3. onlime.toml — [names.email_to_name] + [names.known_contacts]
  4. onlime.toml — [kakao.nickname_to_name] (manual overrides, highest priority)

Matching strategy:
  1. Exact match against full name DB
  2. Strip Korean honorific suffixes, try exact match
  3. Match against given names (surname removed)
  4. Substring: nickname contains a known given name
"""
from __future__ import annotations

import csv
import logging
import re
from functools import lru_cache
from pathlib import Path

from onlime.config import get_settings

logger = logging.getLogger(__name__)

# Korean surname set (covers ~99% of Korean surnames)
_SURNAMES = set(
    "김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽성차주우구신임라진"
)

# Honorific / affectionate suffixes to strip when fuzzy-matching
_SUFFIXES = [
    "이형", "이누나", "이언니", "이오빠",
    "형", "누나", "언니", "오빠",
    "님", "씨", "아", "야", "이",
]
# Sort longest first so "이형" is tried before "이" or "형"
_SUFFIXES.sort(key=len, reverse=True)

_KOREAN_RE = re.compile(r"[가-힣]{2,4}")


def _is_korean_person_name(name: str) -> bool:
    """2-4 char pure-Korean string starting with a known surname."""
    if not name or not (2 <= len(name) <= 4):
        return False
    if any(c < "\uac00" or c > "\ud7a3" for c in name):
        return False
    return name[0] in _SURNAMES


def _extract_names_from_contacts(csv_path: Path) -> set[str]:
    """Parse Google Contacts CSV and extract plausible Korean person names."""
    names: set[str] = set()
    if not csv_path.is_file():
        logger.debug("contacts.csv not found at %s", csv_path)
        return names

    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                first = row.get("First Name", "").strip()
                last = row.get("Last Name", "").strip()
                combined = f"{first} {last}"

                # Structured: Last(성) + First(이름) if both Korean
                if last and first:
                    lk = "".join(c for c in last if "\uac00" <= c <= "\ud7a3")
                    fk = "".join(c for c in first if "\uac00" <= c <= "\ud7a3")
                    if lk and fk and lk[0] in _SURNAMES and len(lk) == 1 and len(fk) in (1, 2):
                        names.add(lk + fk)

                # Extract from combined text
                for match in _KOREAN_RE.findall(combined):
                    if _is_korean_person_name(match):
                        names.add(match)
    except Exception:
        logger.warning("Failed to parse contacts.csv", exc_info=True)

    return names


def _extract_names_from_obsidian(people_dir: Path) -> set[str]:
    """Extract person names from Obsidian People folder filenames."""
    names: set[str] = set()
    if not people_dir.is_dir():
        logger.debug("People directory not found at %s", people_dir)
        return names

    for md_file in people_dir.glob("*.md"):
        # Strip emoji prefixes (👤, 🙍‍♂️, etc.) and .md
        stem = md_file.stem
        # Remove leading emoji/special chars
        clean = re.sub(r"^[^\w가-힣]+", "", stem).strip()
        # Extract Korean names from the cleaned filename
        for match in _KOREAN_RE.findall(clean):
            if _is_korean_person_name(match):
                names.add(match)

    return names


def _strip_suffix(nickname: str) -> str:
    """Remove Korean honorific/affectionate suffixes."""
    for suffix in _SUFFIXES:
        if nickname.endswith(suffix) and len(nickname) > len(suffix):
            return nickname[: -len(suffix)]
    return nickname


class NameResolver:
    """Auto-resolves KakaoTalk nicknames to real names using multiple data sources."""

    def __init__(
        self,
        contacts_csv: Path | None = None,
        people_dir: Path | None = None,
        manual_overrides: dict[str, str] | None = None,
    ) -> None:
        settings = get_settings()

        # --- 1. Collect all known full names ---
        all_names: set[str] = set()

        # From email_to_name
        all_names.update(settings.names.email_to_name.values())

        # From known_contacts
        all_names.update(settings.names.known_contacts)

        # From contacts.csv
        csv_path = contacts_csv or (Path.cwd() / "contacts.csv")
        contact_names = _extract_names_from_contacts(csv_path)
        all_names.update(contact_names)

        # From Obsidian People folder
        p_dir = people_dir or settings.vault.people_path
        obsidian_names = _extract_names_from_obsidian(p_dir)
        all_names.update(obsidian_names)

        # Filter to valid person names only
        self._full_names: set[str] = {n for n in all_names if _is_korean_person_name(n)}

        # --- 2. Build given-name → full-name index ---
        # "정혁" → "심정혁", "욱영" → "김욱영"
        # Priority: email_to_name > known_contacts > contacts.csv/obsidian
        # Higher-priority sources overwrite lower-priority entries.
        self._given_to_full: dict[str, str] = {}

        # Low priority first: contacts.csv + obsidian
        low_priority = {n for n in (contact_names | obsidian_names) if _is_korean_person_name(n)}
        for name in low_priority:
            given = name[1:]
            if given:
                self._given_to_full[given] = name

        # Medium priority: known_contacts (overwrites low)
        for name in settings.names.known_contacts:
            if _is_korean_person_name(name):
                given = name[1:]
                if given:
                    self._given_to_full[given] = name

        # High priority: email_to_name (overwrites medium)
        for name in settings.names.email_to_name.values():
            if _is_korean_person_name(name):
                given = name[1:]
                if given:
                    self._given_to_full[given] = name

        # --- 3. Manual overrides (highest priority) ---
        self._manual: dict[str, str] = dict(manual_overrides or {})

        logger.info(
            "NameResolver loaded: %d full names, %d given-name entries, %d manual overrides "
            "(sources: %d contacts.csv, %d obsidian)",
            len(self._full_names),
            len(self._given_to_full),
            len(self._manual),
            len(contact_names),
            len(obsidian_names),
        )

    def resolve(self, nickname: str) -> str:
        """Resolve a KakaoTalk nickname to a real name.

        Priority:
          1. Manual override (from [kakao.nickname_to_name])
          2. Exact match against full names
          3. Strip honorifics → exact match
          4. Strip honorifics → given-name match
          5. Substring: nickname contains a known given name
          6. Fallback: return nickname as-is
        """
        nick = nickname.strip()
        if not nick:
            return nickname

        # 1. Manual override
        if nick in self._manual:
            return self._manual[nick]

        # 2. Exact match against full names
        if nick in self._full_names:
            return nick

        # 3-4. Strip suffixes and retry
        stripped = _strip_suffix(nick)
        if stripped != nick:
            if stripped in self._full_names:
                return stripped
            if stripped in self._given_to_full:
                return self._given_to_full[stripped]

        # 4b. Given-name match without stripping (e.g., "정혁" directly)
        if nick in self._given_to_full:
            return self._given_to_full[nick]

        # 5. Substring: does the nickname contain a known given name?
        #    Only try for nicknames that are mostly Korean and short-ish
        if len(nick) <= 8:
            for given, full in self._given_to_full.items():
                if len(given) >= 2 and given in nick:
                    return full

        # 6. Fallback
        return nickname


@lru_cache(maxsize=1)
def get_resolver() -> NameResolver:
    """Get the cached global NameResolver instance."""
    settings = get_settings()
    manual = settings.kakao.nickname_to_name if hasattr(settings, "kakao") else {}
    return NameResolver(manual_overrides=manual)
