#!/usr/bin/env python3
"""Bidirectional sync between Obsidian vault and RPG quest system.

Runs every 5 minutes:
  - Obsidian → Game: New/modified tasks become quests, checked tasks mark quests complete
  - Game → Obsidian: Completed quests check off tasks in daily/meeting notes
"""
from __future__ import annotations

import json
import re
import sys
import time
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).parent.parent))
from vault_io import read_note, write_note

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
DAILY_DIR = VAULT_ROOT / "1. THINK" / "매일"
MEETING_DIR = VAULT_ROOT / "0. INPUT" / "Meeting"
DATA_DIR = Path(__file__).parent / "data"
SYNC_STATE_FILE = DATA_DIR / "sync_state.json"
COMPLETED_FILE = DATA_DIR / "game_completed.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger("sync")

# Quest difficulty keywords (refined)
DIFFICULTY_RULES = {
    "S": {
        "keywords": ["창당", "시스템 구축", "플랫폼 개발", "아키텍처", "전략 수립", "투자 유치"],
        "min_words": 8,
    },
    "A": {
        "keywords": ["개발", "구축", "설계", "기획", "채용", "계약서", "제안서", "발표"],
        "min_words": 5,
    },
    "B": {
        "keywords": ["미팅", "검토", "정리", "확인", "섭외", "연결", "조율", "준비", "작성"],
        "min_words": 3,
    },
    "C": {
        "keywords": ["전달", "확인", "시작", "등록", "공유", "연락", "답변"],
        "min_words": 0,
    },
}

XP_MAP = {"S": 100, "A": 50, "B": 25, "C": 10}

# Words indicating scheduling (→ higher difficulty)
SCHEDULE_WORDS = ["일정", "미팅", "회의", "컨퍼런스", "발표"]
# Words indicating creation (→ higher difficulty)
CREATE_WORDS = ["만들기", "제작", "개발", "구현", "설계", "기획", "작성"]


def quest_id(text: str, source: str) -> str:
    return hashlib.md5(f"{source}:{text}".encode()).hexdigest()[:12]


def estimate_difficulty(text: str) -> str:
    """Smart difficulty estimation based on task complexity."""
    t = text.lower().strip()

    # Check for explicit difficulty markers
    for rank in ["S", "A", "B", "C"]:
        for kw in DIFFICULTY_RULES[rank]["keywords"]:
            if kw in t:
                return rank

    # Heuristic: longer tasks tend to be more complex
    word_count = len(t.split())
    if word_count >= 10:
        return "A"
    if word_count >= 6:
        return "B"

    # Check for creation/development tasks
    if any(w in t for w in CREATE_WORDS):
        return "A"

    # Check for scheduling tasks
    if any(w in t for w in SCHEDULE_WORDS):
        return "B"

    # Sub-tasks (indented) are usually simpler
    return "C"


def extract_tasks_from_daily(daily_path: Path, date_str: str) -> list[dict]:
    """Extract all tasks from a daily note."""
    try:
        fm, body = read_note(daily_path)
    except Exception:
        return []

    tasks = []
    current_guild = None
    lines = body.split('\n')

    for line_num, line in enumerate(lines):
        stripped = line.strip()

        # Detect guild headers
        if stripped.startswith('#### ') and not stripped.startswith('#### [['):
            header = stripped[5:].strip()
            guilds = ["참치상사", "에이아이당", "더해커톤", "넥스트노벨", "자기계발"]
            current_guild = None
            for g in guilds:
                if g in header:
                    current_guild = g
                    break
            if not current_guild and header not in ["오늘의 일정", "문장", "생성", "변형"]:
                current_guild = header
            continue

        if stripped.startswith('---'):
            current_guild = None
            continue

        # Task line: - [ ] or - [x]
        task_match = re.match(r'^(\s*)-\s*\[([ xX])\]\s*(.+)', line)
        if not task_match:
            continue

        indent = task_match.group(1)
        checked = task_match.group(2).lower() == 'x'
        task_text = task_match.group(3).strip()

        if not task_text:
            continue

        # Clean display text
        display = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m.group(2) or m.group(1), task_text)

        # Extract mentioned people (exclude 최동인)
        mentioned = []
        for m in re.finditer(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', task_text):
            name = m.group(1)
            if name != '최동인' and not name.startswith('🏷'):
                mentioned.append(name)

        diff = estimate_difficulty(task_text)
        is_subtask = len(indent) > 0

        task = {
            "id": quest_id(task_text, date_str),
            "title": display,
            "rawText": task_text,
            "guild": current_guild,
            "difficulty": diff,
            "xp": XP_MAP[diff],
            "source": f"daily:{date_str}",
            "sourceFile": str(daily_path.relative_to(VAULT_ROOT)),
            "sourceLine": line_num,
            "date": date_str,
            "npcIds": mentioned,
            "completed": checked,
            "type": "daily",
            "isSubtask": is_subtask,
        }
        tasks.append(task)

    return tasks


def extract_tasks_from_meeting(meeting_path: Path) -> list[dict]:
    """Extract action items from meeting note."""
    try:
        fm, body = read_note(meeting_path)
    except Exception:
        return []

    tasks = []
    in_action = False
    title = meeting_path.stem.split('_', 1)[1].replace('_Meeting', '').replace('_', ' ') if '_' in meeting_path.stem else meeting_path.stem
    date_str = meeting_path.stem[:8] if meeting_path.stem[:8].isdigit() else fm.get('created', '')[:10]

    participants = []
    for p in fm.get('participants', []):
        name = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', str(p))
        if name != '최동인':
            participants.append(name)

    for line_num, line in enumerate(body.split('\n')):
        stripped = line.strip()

        if '## 액션 아이템' in stripped:
            in_action = True
            continue
        if in_action and stripped.startswith('## '):
            break

        if not in_action:
            continue

        task_match = re.match(r'^-\s*\[([ xX])\]\s*(.+)', stripped)
        if not task_match:
            continue

        checked = task_match.group(1).lower() == 'x'
        task_text = task_match.group(2).strip()

        if not task_text or '담당자' in task_text:
            continue

        display = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m.group(2) or m.group(1), task_text)
        diff = estimate_difficulty(task_text)

        task = {
            "id": quest_id(task_text, str(meeting_path)),
            "title": f"[{title}] {display}",
            "rawText": task_text,
            "guild": None,
            "difficulty": diff,
            "xp": XP_MAP[diff],
            "source": f"meeting:{meeting_path.stem}",
            "sourceFile": str(meeting_path.relative_to(VAULT_ROOT)),
            "sourceLine": line_num,
            "date": date_str,
            "npcIds": participants,
            "completed": checked,
            "type": "meeting",
        }
        tasks.append(task)

    return tasks


def sync_game_to_obsidian():
    """Write game completions back to Obsidian vault (check off tasks)."""
    completed_path = COMPLETED_FILE
    if not completed_path.exists():
        return 0

    completed_ids = set(json.loads(completed_path.read_text()))
    if not completed_ids:
        return 0

    # Load current quests to find source file and line info
    quests_path = DATA_DIR / "quests.json"
    if not quests_path.exists():
        return 0

    quests_data = json.loads(quests_path.read_text())
    all_quests = (quests_data.get("active", []) or []) + (quests_data.get("completed", []) or [])

    quest_map = {q["id"]: q for q in all_quests if "id" in q}
    updated_files = set()
    changes = 0

    for qid in list(completed_ids):
        quest = quest_map.get(qid)
        if not quest:
            continue

        source_file = quest.get("sourceFile")
        raw_text = quest.get("rawText")
        if not source_file or not raw_text:
            continue

        fpath = VAULT_ROOT / source_file
        if not fpath.exists():
            continue

        try:
            content = fpath.read_text(encoding='utf-8')
        except Exception:
            continue

        # Find the unchecked task line and check it
        old_pattern = f"- [ ] {raw_text}"
        new_pattern = f"- [x] {raw_text}"

        if old_pattern in content:
            content = content.replace(old_pattern, new_pattern, 1)
            fpath.write_text(content, encoding='utf-8')
            changes += 1
            updated_files.add(fpath.name)
            logger.info(f"  Checked off: {raw_text[:40]}... in {fpath.name}")

    if changes:
        logger.info(f"Game → Obsidian: {changes} tasks checked off in {len(updated_files)} files")

    return changes


def full_sync():
    """Run full bidirectional sync."""
    logger.info("=== Sync started ===")

    # 1. Game → Obsidian (check off completed quests)
    game_changes = sync_game_to_obsidian()

    # 2. Obsidian → Game (extract fresh quests)
    all_tasks = []
    today = datetime.now()

    # Recent daily notes (last 14 days)
    for i in range(14):
        d = today - timedelta(days=i)
        date_str = d.strftime('%Y-%m-%d')
        daily_path = DAILY_DIR / f"{date_str}.md"
        if daily_path.exists():
            tasks = extract_tasks_from_daily(daily_path, date_str)
            all_tasks.extend(tasks)

    # Meeting notes (all)
    for mp in sorted(MEETING_DIR.glob("*_Meeting.md")):
        tasks = extract_tasks_from_meeting(mp)
        all_tasks.extend(tasks)

    active = [t for t in all_tasks if not t.get("completed")]
    completed = [t for t in all_tasks if t.get("completed")]

    # Preserve game-completed state
    game_completed = set()
    if COMPLETED_FILE.exists():
        game_completed = set(json.loads(COMPLETED_FILE.read_text()))

    # Move game-completed from active to completed
    still_active = []
    for t in active:
        if t["id"] in game_completed:
            t["completed"] = True
            completed.append(t)
        else:
            still_active.append(t)
    active = still_active

    # Guild info
    guilds = {
        "참치상사": {"icon": "fish", "color": "#FF6B6B", "type": "company"},
        "에이아이당": {"icon": "robot", "color": "#339AF0", "type": "party"},
        "더해커톤": {"icon": "trophy", "color": "#51CF66", "type": "event"},
        "넥스트노벨": {"icon": "book", "color": "#CC5DE8", "type": "org"},
        "자기계발": {"icon": "star", "color": "#FFD43B", "type": "personal"},
    }

    # Epic quests
    epics = [
        {
            "id": "epic_chamchi_minsim",
            "title": "민심맨 프로젝트 완성",
            "description": "AI 기반 정치 여론 분석 시스템 '민심맨'을 완성하고 전국 의원실에 보급한다",
            "guild": "참치상사", "difficulty": "S", "xp": 500, "type": "epic",
            "subQuests": ["민심맨 계약서 작성", "민심맨 고도화", "의원실 파일럿"], "progress": 0,
        },
        {
            "id": "epic_ai_party",
            "title": "에이아이당 창당",
            "description": "대한민국 최초의 AI 정당을 창당하고 AI 대전환 시대의 비전을 제시한다",
            "guild": "에이아이당", "difficulty": "S", "xp": 1000, "type": "epic",
            "subQuests": ["창당준비위원회 구성", "AI 개발자 채용", "당원 100명 모집"], "progress": 0,
        },
        {
            "id": "epic_hackathon",
            "title": "더해커톤 런칭",
            "description": "해커톤 플랫폼을 런칭하고 첫 번째 해커톤을 성공적으로 개최한다",
            "guild": "더해커톤", "difficulty": "A", "xp": 300, "type": "epic",
            "subQuests": ["인플루언서 시딩", "캔디드 연동", "첫 해커톤 개최"], "progress": 0,
        },
        {
            "id": "epic_nextnobel",
            "title": "넥스트노벨 설립",
            "description": "넥스트노벨 단체를 공식 등록하고 첫 프로그램을 운영한다",
            "guild": "넥스트노벨", "difficulty": "A", "xp": 300, "type": "epic",
            "subQuests": ["단체 등록 접수", "참가자 섭외", "첫 모임 개최"], "progress": 0,
        },
    ]

    # Save quests
    quests_output = {
        "active": active,
        "completed": completed,
        "epics": epics,
        "guilds": guilds,
        "lastSync": datetime.now().isoformat(),
    }
    (DATA_DIR / "quests.json").write_text(json.dumps(quests_output, ensure_ascii=False, indent=2))

    # Update player
    player_path = DATA_DIR / "player.json"
    if player_path.exists():
        player = json.loads(player_path.read_text())
    else:
        player = {
            "name": "최동인", "title": "참치상사 대표", "class": "CEO",
            "level": 1, "xp": 0, "xpToNext": 100,
            "guilds": list(guilds.keys()),
            "stats": {"leadership": 5, "networking": 5, "execution": 5, "vision": 5, "creativity": 5},
            "titles": ["신입 모험가"], "completedQuests": 0, "streak": 0,
        }

    total_completed = len(completed) + len(game_completed)
    total_xp = sum(t.get("xp", 10) for t in completed)
    player["completedQuests"] = total_completed

    # Don't overwrite in-game level progress if it's higher
    file_xp_level = 1 + total_xp // 100
    if player.get("level", 1) < file_xp_level:
        player["level"] = file_xp_level
        player["xp"] = total_xp % 100
        player["xpToNext"] = 100 - (total_xp % 100)

    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2))

    # Update NPCs (re-extract)
    from extract_quests import extract_npcs
    npcs = extract_npcs()
    (DATA_DIR / "npcs.json").write_text(json.dumps(npcs, ensure_ascii=False, indent=2))

    logger.info(f"  Active quests: {len(active)}, Completed: {len(completed)}")
    logger.info(f"  Game completions synced to Obsidian: {game_changes}")
    logger.info("=== Sync done ===\n")


def run_daemon(interval=300):
    """Run sync every `interval` seconds (default 5 min)."""
    logger.info(f"Sync daemon started (interval: {interval}s)")
    full_sync()

    while True:
        time.sleep(interval)
        try:
            full_sync()
        except Exception as e:
            logger.error(f"Sync error: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Obsidian ↔ RPG bidirectional sync")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=300, help="Sync interval in seconds (default 300)")
    args = parser.parse_args()

    if args.once:
        full_sync()
    else:
        run_daemon(args.interval)
