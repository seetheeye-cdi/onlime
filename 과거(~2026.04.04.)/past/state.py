"""Persistent sync state tracking to avoid duplicate processing."""
import json
from pathlib import Path
from datetime import datetime


class SyncState:
    def __init__(self, state_file: Path):
        self.path = state_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding='utf-8'))
        return {
            "last_gcal_sync": None,
            "last_plaud_sync": None,
            "processed_events": {},
            "processed_recordings": {},
        }

    def save(self):
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    # --- Google Calendar ---
    def is_event_processed(self, event_id: str, updated: str = None) -> bool:
        entry = self.data["processed_events"].get(event_id)
        if not entry:
            return False
        # Re-process if event was updated after our last sync
        if updated and entry.get("event_updated") != updated:
            return False
        return True

    def mark_event_processed(self, event_id: str, note_path: str, event_updated: str = None):
        self.data["processed_events"][event_id] = {
            "note_path": str(note_path),
            "event_updated": event_updated,
            "synced_at": datetime.now().isoformat(),
        }

    # --- Plaud ---
    def is_recording_processed(self, file_id: str) -> bool:
        return file_id in self.data["processed_recordings"]

    def mark_recording_processed(self, file_id: str, matched_event: str = None, note_path: str = None):
        self.data["processed_recordings"][file_id] = {
            "matched_event": matched_event,
            "note_path": str(note_path) if note_path else None,
            "synced_at": datetime.now().isoformat(),
        }

    def update_last_gcal_sync(self):
        self.data["last_gcal_sync"] = datetime.now().isoformat()

    def update_last_plaud_sync(self):
        self.data["last_plaud_sync"] = datetime.now().isoformat()
