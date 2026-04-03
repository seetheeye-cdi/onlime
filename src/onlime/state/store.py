"""Persistent sync state tracking (v2 schema with per-connector state).

Ported from past/state.py with v2 schema supporting connector-scoped state.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

SCHEMA_VERSION = 2


class SyncState:
    def __init__(self, state_file: Path):
        self.path = state_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            text = self.path.read_text(encoding='utf-8').strip()
            if not text:
                return self._empty_state()
            raw = json.loads(text)
            if raw.get("schema_version", 1) < SCHEMA_VERSION:
                return self._migrate_v1_to_v2(raw)
            return raw
        return self._empty_state()

    @staticmethod
    def _empty_state() -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "connectors": {
                "gcal": {
                    "last_sync": None,
                    "processed": {},
                },
                "plaud": {
                    "last_sync": None,
                    "processed": {},
                },
            },
        }

    @staticmethod
    def _migrate_v1_to_v2(v1: dict) -> dict:
        """Migrate v1 flat state to v2 connector-scoped state."""
        return {
            "schema_version": SCHEMA_VERSION,
            "connectors": {
                "gcal": {
                    "last_sync": v1.get("last_gcal_sync"),
                    "processed": v1.get("processed_events", {}),
                },
                "plaud": {
                    "last_sync": v1.get("last_plaud_sync"),
                    "processed": v1.get("processed_recordings", {}),
                },
            },
        }

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

    def _connector(self, name: str) -> dict:
        """Get or create connector state section."""
        connectors = self.data.setdefault("connectors", {})
        return connectors.setdefault(name, {"last_sync": None, "processed": {}})

    # --- Google Calendar ---
    def is_event_processed(self, event_id: str, updated: str | None = None) -> bool:
        entry = self._connector("gcal")["processed"].get(event_id)
        if not entry:
            return False
        if updated and entry.get("event_updated") != updated:
            return False
        return True

    def mark_event_processed(self, event_id: str, note_path: str, event_updated: str | None = None) -> None:
        self._connector("gcal")["processed"][event_id] = {
            "note_path": str(note_path),
            "event_updated": event_updated,
            "synced_at": datetime.now().isoformat(),
        }

    def update_last_gcal_sync(self) -> None:
        self._connector("gcal")["last_sync"] = datetime.now().isoformat()

    # --- Plaud ---
    def is_recording_processed(self, file_id: str) -> bool:
        return file_id in self._connector("plaud")["processed"]

    def mark_recording_processed(
        self, file_id: str, matched_event: str | None = None, note_path: str | None = None,
    ) -> None:
        self._connector("plaud")["processed"][file_id] = {
            "matched_event": matched_event,
            "note_path": str(note_path) if note_path else None,
            "synced_at": datetime.now().isoformat(),
        }

    def update_last_plaud_sync(self) -> None:
        self._connector("plaud")["last_sync"] = datetime.now().isoformat()

    # --- Generic connector state ---
    def is_processed(self, connector: str, item_id: str) -> bool:
        return item_id in self._connector(connector)["processed"]

    def mark_processed(self, connector: str, item_id: str, **metadata) -> None:
        self._connector(connector)["processed"][item_id] = {
            **metadata,
            "synced_at": datetime.now().isoformat(),
        }

    def update_last_sync(self, connector: str) -> None:
        self._connector(connector)["last_sync"] = datetime.now().isoformat()
