#!/usr/bin/env python3
"""Migrate from past/obsidian-sync to Onlime.

Copies auth files and converts state from v1 to v2 format.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onlime.config import get_settings
from onlime.state.migration import migrate_state, migrate_auth_files


def main():
    settings = get_settings()
    old_dir = Path.home() / ".config" / "obsidian-sync"
    new_dir = settings.state.resolved_dir

    print(f"마이그레이션: {old_dir} → {new_dir}")
    print()

    if not old_dir.exists():
        print(f"  기존 설정 디렉토리가 없습니다: {old_dir}")
        print("  마이그레이션할 데이터가 없습니다.")
        return

    # Migrate auth files
    migrated = migrate_auth_files(old_dir, new_dir)
    if migrated:
        for f in migrated:
            print(f"  복사: {f}")
    else:
        print("  인증 파일: 이미 최신 또는 복사할 파일 없음")

    # Migrate state
    old_state = old_dir / "state.json"
    new_state = settings.state.state_file
    if migrate_state(old_state, new_state):
        print(f"  상태 마이그레이션 완료 (v1 → v2)")
        print(f"  새 상태 파일: {new_state}")
    else:
        print("  상태 파일: 마이그레이션 불필요")

    print()
    print("완료! 이제 'onlime run --dry-run'으로 테스트하세요.")


if __name__ == '__main__':
    main()
