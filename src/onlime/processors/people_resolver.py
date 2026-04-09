"""PeopleResolver — unified person matching across phone/email/alias/vault.

Composites VaultNameIndex with phone, email, and alias reverse-indexes.
No LLM calls, <5ms per resolve.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import structlog

from onlime.config import get_settings
from onlime.processors.name_resolver import VaultNameIndex

logger = structlog.get_logger()

# Regex to extract phone numbers from People file bodies
_PHONE_RE = re.compile(r"전화[:\s]*([0-9\-+\s]{9,})")
# Regex to extract email addresses from People file bodies
_EMAIL_RE = re.compile(r"이메일[:\s]*([\w.+-]+@[\w.-]+)")

# People directories to scan for phone/email metadata
_PEOPLE_DIRS = [
    "1.INPUT/People",
    "2.OUTPUT/People/Active",
    "2.OUTPUT/People/Network",
    "2.OUTPUT/People/Reference",
]


def _normalize_phone(raw: str) -> str:
    """Normalize a phone number: strip non-digits, handle +82 prefix."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


class PeopleResolver:
    """Unified person resolver: alias → phone → email → VaultNameIndex."""

    def __init__(self, name_index: VaultNameIndex) -> None:
        self._name_index = name_index
        self._phone_to_stem: dict[str, str] = {}
        self._email_to_stem: dict[str, str] = {}
        self._alias_to_stem: dict[str, str] = {}
        self._built = False

    @property
    def stats(self) -> dict[str, int]:
        return {
            "phones": len(self._phone_to_stem),
            "emails": len(self._email_to_stem),
            "aliases": len(self._alias_to_stem),
        }

    def build(self, vault_root: Path) -> None:
        """Build resolver indexes from config + vault People files.

        Called once at startup and again after janitor rebuilds name_index.
        """
        vault = vault_root.expanduser()
        settings = get_settings()

        phone_map: dict[str, str] = {}
        email_map: dict[str, str] = {}
        alias_map: dict[str, str] = {}

        # --- Source 1: onlime.toml config ---
        for alias, name in settings.names.aliases.items():
            canonical = self._name_index.match(name) or name
            alias_map[alias] = canonical

        for phone, name in settings.names.phone_to_name.items():
            canonical = self._name_index.match(name) or name
            phone_map[_normalize_phone(phone)] = canonical

        for email, name in settings.names.email_to_name.items():
            canonical = self._name_index.match(name) or name
            email_map[email.lower()] = canonical

        # KakaoTalk nickname mappings
        for nick, name in settings.kakao.nickname_to_name.items():
            canonical = self._name_index.match(name) or name
            alias_map[nick] = canonical

        # --- Source 2: Vault People file scan ---
        for rel_dir in _PEOPLE_DIRS:
            dir_path = vault / rel_dir
            if not dir_path.is_dir():
                continue
            for md_file in dir_path.rglob("*.md"):
                stem = unicodedata.normalize("NFC", md_file.stem)
                # For People files with tags, use just the name part
                name_part = stem.split("_", 1)[0].strip() if "_" in stem else stem
                canonical = self._name_index.match(name_part) or name_part

                try:
                    content = md_file.read_text("utf-8", errors="replace")
                except OSError:
                    continue

                # Extract phone numbers
                for m in _PHONE_RE.finditer(content):
                    normalized = _normalize_phone(m.group(1))
                    if len(normalized) >= 10:
                        phone_map.setdefault(normalized, canonical)

                # Extract email addresses
                for m in _EMAIL_RE.finditer(content):
                    email_map.setdefault(m.group(1).lower(), canonical)

        self._phone_to_stem = phone_map
        self._email_to_stem = email_map
        self._alias_to_stem = alias_map
        self._built = True

        logger.info(
            "people_resolver.built",
            phones=len(phone_map),
            emails=len(email_map),
            aliases=len(alias_map),
        )

    def resolve(self, identifier: str) -> str | None:
        """Resolve an identifier to a canonical vault stem.

        Cascade:
        1. Exact alias match (config aliases + kakao nicknames)
        2. Phone number match (normalized)
        3. Email match (lowercased)
        4. VaultNameIndex fuzzy match
        5. None (no match)
        """
        if not self._built or not identifier:
            return None

        identifier = identifier.strip()

        # 1. Alias match
        if identifier in self._alias_to_stem:
            return self._alias_to_stem[identifier]

        # 2. Phone number match
        normalized_phone = _normalize_phone(identifier)
        if len(normalized_phone) >= 10 and normalized_phone in self._phone_to_stem:
            return self._phone_to_stem[normalized_phone]

        # 3. Email match
        if "@" in identifier:
            lower_email = identifier.lower()
            if lower_email in self._email_to_stem:
                return self._email_to_stem[lower_email]

        # 4. VaultNameIndex fuzzy match
        matched = self._name_index.match(identifier)
        if matched:
            return matched

        return None

    def resolve_people_list(self, people: list[str]) -> list[str]:
        """Resolve a list of person identifiers, deduplicating."""
        seen: set[str] = set()
        result: list[str] = []
        for p in people:
            resolved = self.resolve(p) or p
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
        return result
