#!/usr/bin/env python3
"""Extract quests, NPCs, and player data from Obsidian vault for RPG system."""
from __future__ import annotations

import json
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from vault_io import read_note

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
PEOPLE_DIR = VAULT_ROOT / "0. INPUT" / "People"
MEETING_DIR = VAULT_ROOT / "0. INPUT" / "Meeting"
DAILY_DIR = VAULT_ROOT / "1. THINK" / "매일"
OUTPUT_DIR = Path(__file__).parent / "data"

# Wiki-link extraction
WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')

# Known project/guild mappings
GUILDS = {
    "참치상사": {"icon": "fish", "color": "#FF6B6B", "type": "company"},
    "에이아이당": {"icon": "robot", "color": "#339AF0", "type": "party"},
    "더해커톤": {"icon": "trophy", "color": "#51CF66", "type": "event"},
    "넥스트노벨": {"icon": "book", "color": "#CC5DE8", "type": "org"},
    "자기계발": {"icon": "star", "color": "#FFD43B", "type": "personal"},
}

# Guild → key team members (quest givers when no specific person mentioned)
GUILD_MEMBERS = {
    "참치상사": ["김석기", "심정혁", "김욱영"],
    "에이아이당": ["양승현"],
    "더해커톤": ["조용민"],
    "넥스트노벨": ["원준환"],
}

# Quest difficulty estimation
DIFFICULTY_S = ["창당", "시스템 구축", "플랫폼 개발", "아키텍처", "전략 수립", "투자 유치", "서비스 런칭"]
DIFFICULTY_A = ["개발", "구축", "설계", "기획", "채용", "계약서", "제안서", "발표", "사업소개서", "제작"]
DIFFICULTY_B = ["미팅", "검토", "정리", "섭외", "연결", "조율", "준비", "작성", "분석", "리서치"]
DIFFICULTY_C = ["전달", "확인", "시작", "등록", "공유", "연락", "답변", "읽기"]

XP_MAP = {"S": 100, "A": 50, "B": 25, "C": 10}

# NPC Category classification
PHILOSOPHERS = {
    "프리드리히 니체", "알베르 까뮈", "자크 데리다", "자크 라캉",
    "지그문트 프로이트", "마르틴 하이데거", "쇼펜하우어", "칼 포퍼",
    "호메로스", "후설", "칸트", "포도르 도스토옙스키", "블레즈 파스칼",
    "파르메니데스", "소포클레스", "에우리피데스", "아이스퀼레스",
    "에피쿠로스", "프로타고라스", "프로메테우스", "크라수스",
    "앨프리드 노스 화이트헤드", "마르쿠스 아우렐리우스", "한병철",
    "피터 드러커",
}

MOGULS = {
    "일론 머스크", "빌 게이츠", "마크 저커버그", "피터 틸",
    "사티아 나델라", "찰리 멍거", "이본 쉬나드", "앤드류 테이트",
    "버락 오바마", "마거릿 대처", "요제프 괴벨스",
    "해리 S. 트루먼", "이명박", "칭기즈칸",
    "조란 맘다니", "샤샤 아이젠버그",
}

ARTISTS = {
    "윤동주", "김동률", "허영만", "마를린 먼로", "오노 지로",
    "크리스토퍼 놀란", "오타니 쇼헤이", "스테판 커리",
    "이창호 기사", "기형도", "김금희", "나희덕", "이상",
    "허준이", "성민지",
}

FICTIONAL = {
    "월터 미티", "란초다스", "Ms.요다", "바이러스 교수",
    "구요한",
}


def classify_npc(npc_id, tags, group_field, meeting_count):
    """Classify NPC into category."""
    if npc_id in PHILOSOPHERS:
        return "philosopher"
    if npc_id in MOGULS:
        return "mogul"
    if npc_id in ARTISTS:
        return "artist"
    if npc_id in FICTIONAL:
        return "fictional"
    if group_field == "가상인물":
        return "fictional"
    if any("fiction" in str(t).lower() for t in (tags or [])):
        return "fictional"
    return "contact"


def extract_bio_text(body: str, max_chars: int = 500) -> str:
    """Extract meaningful dialog text from vault note body."""
    if not body or not body.strip():
        return ""

    text = body
    # Remove image embeds
    text = re.sub(r'!\[\[.*?\]\]', '', text)
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove SYNC blocks
    text = re.sub(r'<!-- SYNC:\S+ -->.*?<!-- /SYNC:\S+ -->', '', text, flags=re.DOTALL)
    # Clean wikilinks
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    # Remove tag references
    text = re.sub(r'#\S+', '', text)
    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+.*$', '', text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)

    lines = [l.strip() for l in text.split('\n')]
    # Remove template fields and very short lines
    lines = [l for l in lines if l and len(l) > 3]
    lines = [l for l in lines if not re.match(
        r'^-\s*(Name|Year|Occupation|Mobile|Office|Email|Address|Instagram|LinkedIn|Facebook|Twitter|Phone|Homepage|Birth):',
        l, re.IGNORECASE
    )]

    text = '\n'.join(lines)

    if len(text) > max_chars:
        truncated = text[:max_chars]
        # Try to cut at sentence boundary
        last_break = max(
            truncated.rfind('다.'), truncated.rfind('요.'),
            truncated.rfind('. '), truncated.rfind('\n'),
            truncated.rfind('다\n'),
        )
        if last_break > max_chars * 0.4:
            text = truncated[:last_break + 1].rstrip()
        else:
            text = truncated.rstrip() + '...'

    return text.strip()


def quest_id(text: str, source: str) -> str:
    """Generate stable quest ID from content."""
    return hashlib.md5(f"{source}:{text}".encode()).hexdigest()[:12]


def estimate_difficulty(text: str) -> str:
    """Smart difficulty estimation based on task complexity."""
    t = text.lower().strip()

    # Check keywords (S→C priority)
    if any(kw in t for kw in DIFFICULTY_S):
        return "S"
    if any(kw in t for kw in DIFFICULTY_A):
        return "A"
    if any(kw in t for kw in DIFFICULTY_B):
        return "B"
    if any(kw in t for kw in DIFFICULTY_C):
        return "C"

    # Heuristic: longer = more complex
    word_count = len(t.split())
    if word_count >= 10:
        return "A"
    if word_count >= 5:
        return "B"

    return "C"


_PEOPLE_STEMS = None

def _get_people_stems():
    global _PEOPLE_STEMS
    if _PEOPLE_STEMS is None:
        _PEOPLE_STEMS = {f.stem for f in PEOPLE_DIR.glob("*.md") if "Template" not in f.stem}
    return _PEOPLE_STEMS


def extract_mentioned_people(text: str) -> list[str]:
    """Extract people from text. Checks [[links]] and plain-text name mentions."""
    people = []
    stems = _get_people_stems()
    seen = set()

    # 1. Wiki-links
    for match in WIKILINK_RE.finditer(text):
        target = match.group(1)
        if target == '최동인':
            continue
        if target in stems and target not in seen:
            people.append(target)
            seen.add(target)

    # 2. Plain-text: check if any People name appears in the task text
    # Extract primary name (first part before _, (, etc.)
    clean_text = re.sub(r'\[\[[^\]]+\]\]', '', text)  # remove wiki-links already handled
    for stem in stems:
        primary = re.split(r'[_(,]', stem)[0].strip()
        if primary == '최동인' or len(primary) < 2:
            continue
        if primary in clean_text and primary not in seen:
            people.append(primary)
            seen.add(primary)

    return people


def extract_daily_quests(daily_path: Path, date_str: str) -> list[dict]:
    """Extract uncompleted tasks from a daily note as quests."""
    try:
        fm, body = read_note(daily_path)
    except Exception:
        return []

    quests = []
    current_guild = None
    lines = body.split('\n')

    for line in lines:
        stripped = line.strip()

        # Detect project/guild headers: #### 프로젝트명
        if stripped.startswith('#### ') and not stripped.startswith('#### [['):
            header = stripped[5:].strip()
            # Check if it matches a known guild
            for guild_name in GUILDS:
                if guild_name in header:
                    current_guild = guild_name
                    break
            else:
                current_guild = header if header and header != "오늘의 일정" else None
            continue

        # Skip horizontal rules and other headers
        if stripped.startswith('---') or stripped.startswith('## ') or stripped.startswith('> '):
            if stripped.startswith('---'):
                current_guild = None
            continue

        # Uncompleted task: - [ ] ...
        if re.match(r'^-?\s*\[ \]', stripped):
            task_text = re.sub(r'^-?\s*\[ \]\s*', '', stripped).strip()
            if not task_text:
                continue

            # Extract people mentioned
            mentioned = extract_mentioned_people(task_text)

            # Clean display text (remove wiki-link syntax)
            display = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m.group(2) or m.group(1), task_text)

            diff = estimate_difficulty(task_text)

            # If no person found, assign guild team members as quest givers
            if not mentioned and current_guild:
                mentioned = GUILD_MEMBERS.get(current_guild, [])[:1]

            quest = {
                "id": quest_id(task_text, date_str),
                "title": display,
                "rawText": task_text,
                "guild": current_guild,
                "guildInfo": GUILDS.get(current_guild, {"icon": "scroll", "color": "#868E96", "type": "misc"}) if current_guild else None,
                "difficulty": diff,
                "xp": XP_MAP[diff],
                "source": f"daily:{date_str}",
                "sourceFile": str(daily_path.relative_to(VAULT_ROOT)),
                "date": date_str,
                "npcIds": mentioned,
                "completed": False,
                "type": "daily",
            }
            quests.append(quest)

        # Completed task (for stats): - [x] ...
        elif re.match(r'^-?\s*\[x\]', stripped, re.IGNORECASE):
            task_text = re.sub(r'^-?\s*\[x\]\s*', '', stripped, flags=re.IGNORECASE).strip()
            if not task_text:
                continue
            display = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m.group(2) or m.group(1), task_text)
            diff = estimate_difficulty(task_text)
            quest = {
                "id": quest_id(task_text, date_str),
                "title": display,
                "guild": current_guild,
                "difficulty": diff,
                "xp": XP_MAP[diff],
                "source": f"daily:{date_str}",
                "date": date_str,
                "completed": True,
                "type": "daily",
            }
            quests.append(quest)

    return quests


def extract_meeting_quests(meeting_path: Path) -> list[dict]:
    """Extract action items from meeting notes."""
    try:
        fm, body = read_note(meeting_path)
    except Exception:
        return []

    quests = []
    in_action_section = False
    title = meeting_path.stem.split('_', 1)[1].replace('_Meeting', '').replace('_', ' ') if '_' in meeting_path.stem else meeting_path.stem
    date_str = meeting_path.stem[:8] if meeting_path.stem[:8].isdigit() else fm.get('created', '')[:10]
    participants = []
    for p in fm.get('participants', []):
        name = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', str(p))
        if name != '최동인':  # Player is not an NPC
            participants.append(name)

    for line in body.split('\n'):
        stripped = line.strip()

        if '## 액션 아이템' in stripped:
            in_action_section = True
            continue
        if in_action_section and stripped.startswith('## '):
            break

        if in_action_section and re.match(r'^-?\s*\[ \]', stripped):
            task_text = re.sub(r'^-?\s*\[ \]\s*', '', stripped).strip()
            if not task_text or task_text.startswith('[[담당자]]'):
                continue

            display = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m.group(2) or m.group(1), task_text)
            diff = estimate_difficulty(task_text)
            npcs = participants

            quest = {
                "id": quest_id(task_text, str(meeting_path)),
                "title": f"[{title}] {display}",
                "rawText": task_text,
                "guild": None,
                "difficulty": diff,
                "xp": XP_MAP[diff],
                "source": f"meeting:{meeting_path.stem}",
                "sourceFile": str(meeting_path.relative_to(VAULT_ROOT)),
                "date": date_str,
                "npcIds": npcs,
                "completed": False,
                "type": "meeting",
            }
            quests.append(quest)

    return quests


def extract_npcs() -> list[dict]:
    """Extract NPC data from People folder."""
    npcs = []
    meeting_count = {}

    # Count meetings per person
    for mp in MEETING_DIR.glob("*_Meeting.md"):
        try:
            fm, _ = read_note(mp)
            for p in fm.get('participants', []):
                name = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', str(p))
                meeting_count[name] = meeting_count.get(name, 0) + 1
        except Exception:
            pass

    for f in sorted(PEOPLE_DIR.glob("*.md")):
        if "Template" in f.stem:
            continue

        stem = f.stem
        # Clean name: remove emoji prefixes
        clean = re.sub(r'^[^\w가-힣]+', '', stem).strip()
        primary = re.split(r'[_(,]', clean)[0].strip()

        # Read frontmatter for tags/type
        try:
            fm, body = read_note(f)
        except Exception:
            fm, body = {}, ""

        tags = fm.get('tags', [])
        if isinstance(tags, str):
            tags = [tags]

        # Extract affiliation from name or tags
        affiliation = ""
        parts = re.split(r'[_,]', clean)
        if len(parts) > 1:
            affiliation = parts[1].strip()

        # Determine NPC role/class based on tags/affiliation
        npc_class = "merchant"  # default
        aff_lower = (affiliation or '').lower()
        if any(kw in aff_lower for kw in ['개발', 'dev', 'engineer', 'cto']):
            npc_class = "engineer"
        elif any(kw in aff_lower for kw in ['투자', 'invest', 'vc', 'fund']):
            npc_class = "investor"
        elif any(kw in aff_lower for kw in ['의원', '정치', '국회', '당']):
            npc_class = "politician"
        elif any(kw in aff_lower for kw in ['대표', 'ceo', '창업']):
            npc_class = "founder"
        elif any(kw in aff_lower for kw in ['디자인', 'design', 'ui']):
            npc_class = "designer"
        elif any(kw in aff_lower for kw in ['교수', '박사', '연구']):
            npc_class = "scholar"

        meetings = meeting_count.get(primary, 0) + meeting_count.get(stem, 0)

        # Classify NPC category
        group_field = fm.get("group", "")
        category = classify_npc(primary, tags, group_field, meetings)

        # Extract bio text from note body
        bio = extract_bio_text(body)

        npc = {
            "id": primary,
            "fullName": stem,
            "displayName": primary,
            "affiliation": affiliation,
            "class": npc_class,
            "category": category,
            "bio": bio,
            "vaultPath": str(f.relative_to(VAULT_ROOT)),
            "tags": tags,
            "meetingCount": meetings,
            "level": min(10, 1 + meetings),
        }
        npcs.append(npc)

    return npcs


def build_player() -> dict:
    """Build initial player profile."""
    return {
        "name": "최동인",
        "title": "참치상사 대표",
        "class": "CEO",
        "level": 1,
        "xp": 0,
        "xpToNext": 100,
        "guilds": list(GUILDS.keys()),
        "stats": {
            "leadership": 5,
            "networking": 5,
            "execution": 5,
            "vision": 5,
            "creativity": 5,
        },
        "titles": ["신입 모험가"],
        "completedQuests": 0,
        "streak": 0,
    }


def build_epic_quests() -> list[dict]:
    """Build epic quest lines from major projects."""
    epics = [
        {
            "id": "epic_chamchi_minsim",
            "title": "민심맨 프로젝트 완성",
            "description": "AI 기반 정치 여론 분석 시스템 '민심맨'을 완성하고 전국 의원실에 보급한다",
            "guild": "참치상사",
            "difficulty": "S",
            "xp": 500,
            "type": "epic",
            "subQuests": ["민심맨 계약서 작성", "민심맨 고도화", "의원실 파일럿"],
            "progress": 0,
        },
        {
            "id": "epic_ai_party",
            "title": "에이아이당 창당",
            "description": "대한민국 최초의 AI 정당을 창당하고 AI 대전환 시대의 비전을 제시한다",
            "guild": "에이아이당",
            "difficulty": "S",
            "xp": 1000,
            "type": "epic",
            "subQuests": ["창당준비위원회 구성", "AI 개발자 채용", "당원 100명 모집"],
            "progress": 0,
        },
        {
            "id": "epic_hackathon",
            "title": "더해커톤 런칭",
            "description": "해커톤 플랫폼을 런칭하고 첫 번째 해커톤을 성공적으로 개최한다",
            "guild": "더해커톤",
            "difficulty": "A",
            "xp": 300,
            "type": "epic",
            "subQuests": ["인플루언서 시딩", "캔디드 연동", "첫 해커톤 개최"],
            "progress": 0,
        },
        {
            "id": "epic_nextnobel",
            "title": "넥스트노벨 설립",
            "description": "넥스트노벨 단체를 공식 등록하고 첫 프로그램을 운영한다",
            "guild": "넥스트노벨",
            "difficulty": "A",
            "xp": 300,
            "type": "epic",
            "subQuests": ["단체 등록 접수", "참가자 섭외", "첫 모임 개최"],
            "progress": 0,
        },
    ]
    return epics


def main():
    print("Extracting quests and NPCs from vault...")

    # Extract quests from recent daily notes (last 30 days)
    all_quests = []
    today = datetime.now()

    for i in range(30):
        d = today - timedelta(days=i)
        date_str = d.strftime('%Y-%m-%d')
        daily_path = DAILY_DIR / f"{date_str}.md"
        if daily_path.exists():
            quests = extract_daily_quests(daily_path, date_str)
            all_quests.extend(quests)

    # Extract quests from meeting notes
    for mp in sorted(MEETING_DIR.glob("*_Meeting.md")):
        quests = extract_meeting_quests(mp)
        all_quests.extend(quests)

    # Count stats
    active_quests = [q for q in all_quests if not q.get("completed")]
    completed_quests = [q for q in all_quests if q.get("completed")]

    print(f"  Active quests: {len(active_quests)}")
    print(f"  Completed quests: {len(completed_quests)}")

    # Extract NPCs
    npcs = extract_npcs()
    print(f"  NPCs: {len(npcs)}")

    # Build player
    player = build_player()
    # Credit completed quests
    player["completedQuests"] = len(completed_quests)
    total_xp = sum(q.get("xp", 10) for q in completed_quests)
    player["xp"] = total_xp % 100
    player["level"] = max(1, 1 + total_xp // 100)
    player["xpToNext"] = 100 - (total_xp % 100)

    # Update title based on level
    titles = [
        (1, "신입 모험가"), (3, "숙련된 전략가"), (5, "능숙한 사업가"),
        (8, "전설의 리더"), (12, "세계를 바꾸는 자"), (20, "CEO of CEOs"),
    ]
    for lvl, title in reversed(titles):
        if player["level"] >= lvl:
            player["titles"] = [title]
            break

    # Epic quests
    epics = build_epic_quests()

    # Guild summary
    guild_stats = {}
    for q in all_quests:
        g = q.get("guild") or "기타"
        if g not in guild_stats:
            guild_stats[g] = {"active": 0, "completed": 0}
        if q.get("completed"):
            guild_stats[g]["completed"] += 1
        else:
            guild_stats[g]["active"] += 1

    print(f"\n  Player Level: {player['level']} ({total_xp} XP)")
    print(f"  Title: {player['titles'][0]}")
    print(f"\n  Guild breakdown:")
    for g, stats in sorted(guild_stats.items()):
        print(f"    {g}: {stats['active']} active, {stats['completed']} done")

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUTPUT_DIR / "quests.json").write_text(
        json.dumps({"active": active_quests, "completed": completed_quests, "epics": epics, "guilds": GUILDS}, ensure_ascii=False, indent=2)
    )
    (OUTPUT_DIR / "npcs.json").write_text(
        json.dumps(npcs, ensure_ascii=False, indent=2)
    )
    (OUTPUT_DIR / "player.json").write_text(
        json.dumps(player, ensure_ascii=False, indent=2)
    )

    print(f"\nOutput saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
