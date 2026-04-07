"""Migrate state from v1 (past/obsidian-sync) to v2 (onlime)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from onlime.state.store import SyncState, SCHEMA_VERSION


def migrate_state(old_state_file: Path, new_state_file: Path) -> bool:
    """Migrate v1 state file to v2 format at new location.

    Returns True if migration was performed, False if skipped.
    """
    if not old_state_file.exists():
        return False

    if new_state_file.exists():
        existing = json.loads(new_state_file.read_text(encoding='utf-8'))
        if existing.get("schema_version", 1) >= SCHEMA_VERSION:
            return False

    # Backup old state
    backup = old_state_file.with_suffix('.json.bak')
    if not backup.exists():
        shutil.copy2(old_state_file, backup)

    # Load and migrate
    v1_data = json.loads(old_state_file.read_text(encoding='utf-8'))
    v2_data = SyncState._migrate_v1_to_v2(v1_data)

    new_state_file.parent.mkdir(parents=True, exist_ok=True)
    new_state_file.write_text(
        json.dumps(v2_data, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    return True


def migrate_auth_files(old_config_dir: Path, new_config_dir: Path) -> list[str]:
    """Copy auth files (credentials, tokens) from old config to new location.

    Returns list of migrated file names.
    """
    new_config_dir.mkdir(parents=True, exist_ok=True)
    migrated = []

    auth_files = [
        "credentials.json",
        "token.json",
        "plaud_token.txt",
        "plaud_config.json",
    ]

    for fname in auth_files:
        src = old_config_dir / fname
        dst = new_config_dir / fname
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            migrated.append(fname)

    return migrated
