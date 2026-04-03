"""
주간회고 자동화 스크립트 (Python fallback)

Plaud 녹음 + Claude Code 세션 데이터를 수집하고,
Claude API로 10개 관점 분석을 수행한 뒤 옵시디언에 저장한다.

Usage:
    python weekly_review.py                    # 지난주 자동 계산
    python weekly_review.py --start 2026-03-24 --end 2026-03-30
    python weekly_review.py --dry-run          # 파일 저장 없이 미리보기
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import os
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import httpx

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
TZ = ZoneInfo("Asia/Seoul")
VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
WEEKLY_DIR = VAULT_ROOT / "2. OUTPUT" / "Weekly"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

PLAUD_CONFIG_PATHS = [
    Path.home() / ".config" / "onlime" / "plaud_config.json",
    Path.home() / ".config" / "obsidian-sync" / "plaud_config.json",
]
PLAUD_API_BASE = "https://api-apne1.plaud.ai"

PROFILE = """최동인, 01년생 (만 25세), 고려대 경영학과 4학년 (휴학 중)
참치상사 (참된 정치를 파는 회사) 대표
포드스테이트(Fordstate) 내러티브 홀딩컴퍼니 창업자"""

ANALYST_ROLES = [
    ("사업 전략 분석가", "사업 포트폴리오, 시장 기회, 경쟁 우위", "어떤 사업에 집중해야 하는가?"),
    ("인사/조직 분석가", "팀 구조, 인재 관리, 조직 문화, 리더십", "조직이 지속 가능한가?"),
    ("정치 전략 분석가", "정치적 포지셔닝, 정당 전략, 정책 방향", "정치적 리스크와 기회는?"),
    ("제품/기술 분석가", "기술 스택, 제품 완성도, 기술 부채", "기술적으로 가장 유망/위험한 제품은?"),
    ("재무/리스크 분석가", "현금 흐름, 비용 구조, 수익 모델", "재무적으로 지속 가능한가?"),
    ("위기관리/PR 분석가", "평판 리스크, 법적 리스크, 보안", "가장 큰 위기 벡터는?"),
    ("네트워킹/관계 분석가", "인맥, 관계 자산, 팔로업 전략", "가장 가치 있는 관계와 팔로업 우선순위는?"),
    ("실행력/생산성 분석가", "시간 배분, 효율, 약속 이행률", "실행력의 병목은 어디인가?"),
    ("개인 성장/심리 분석가", "멘탈, 번아웃, 자기 인식, 성장", "지속 가능한 페이스인가?"),
    ("종합 전략 자문가", "위 9개 관점 통합, 전체 방향성", "이번 주 가장 중요한 의사결정은?"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Date helpers
# ──────────────────────────────────────────────
def get_date_range(start_str: str | None, end_str: str | None) -> tuple[date, date]:
    """Calculate the review period. Defaults to last Mon-Sun."""
    if start_str and end_str:
        return date.fromisoformat(start_str), date.fromisoformat(end_str)
    today = date.today()
    # Last Sunday
    end = today - timedelta(days=today.isoweekday())
    # Last Monday
    start = end - timedelta(days=6)
    return start, end


def iso_week_label(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# ──────────────────────────────────────────────
# Plaud API
# ──────────────────────────────────────────────
def get_plaud_token() -> str | None:
    for path in PLAUD_CONFIG_PATHS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text())
                token = cfg.get("token") or cfg.get("accessToken")
                if token:
                    return token
            except (json.JSONDecodeError, KeyError):
                continue
    return os.environ.get("PLAUD_TOKEN")


def plaud_headers(token: str) -> dict:
    return {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "Origin": "https://web.plaud.ai",
        "Referer": "https://web.plaud.ai/",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }


async def fetch_plaud_recordings(
    client: httpx.AsyncClient, token: str, start: date, end: date
) -> list[dict]:
    """Fetch Plaud recordings within date range."""
    start_ts = int(datetime.combine(start, datetime.min.time(), tzinfo=TZ).timestamp() * 1000)
    end_ts = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=TZ).timestamp() * 1000)

    all_recs = []
    page = 1
    while True:
        resp = await client.get(
            f"{PLAUD_API_BASE}/file/simple/web",
            params={"page": page, "pageSize": 200},
            headers=plaud_headers(token),
        )
        resp.raise_for_status()
        data = resp.json()
        recs = data.get("data_file_list", [])
        if not recs:
            break
        for r in recs:
            st = r.get("start_time", 0)
            if start_ts <= st < end_ts:
                all_recs.append(r)
        if len(recs) < 200:
            break
        page += 1

    logger.info(f"Plaud: {len(all_recs)} recordings in range")
    return sorted(all_recs, key=lambda r: r.get("start_time", 0))


async def fetch_plaud_summary(
    client: httpx.AsyncClient, token: str, file_id: str
) -> str | None:
    """Fetch AI summary for a recording."""
    try:
        resp = await client.get(
            f"{PLAUD_API_BASE}/file/detail/{file_id}",
            headers=plaud_headers(token),
        )
        resp.raise_for_status()
        detail = resp.json()
        for item in detail.get("data", {}).get("content_list", []):
            if item.get("data_type") == "auto_sum_note" and item.get("task_status") == 1:
                link = item.get("data_link")
                if link:
                    s3_resp = await client.get(link)
                    s3_resp.raise_for_status()
                    raw = s3_resp.content
                    try:
                        raw = gzip.decompress(raw)
                    except (gzip.BadGzipFile, OSError):
                        pass
                    text = raw.decode("utf-8", errors="replace")
                    if text.lstrip().startswith("{"):
                        try:
                            d = json.loads(text)
                            if "ai_content" in d:
                                text = d["ai_content"]
                        except json.JSONDecodeError:
                            pass
                    lines = [l for l in text.split("\n") if not l.startswith("![PLAUD NOTE]")]
                    return "\n".join(lines).strip()
    except httpx.HTTPError as e:
        logger.warning(f"Summary fetch failed for {file_id}: {e}")
    return None


# ──────────────────────────────────────────────
# Claude Code Sessions
# ──────────────────────────────────────────────
def collect_claude_sessions(start: date, end: date) -> dict[str, list[str]]:
    """Collect Claude Code session user messages, grouped by project."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())

    projects: dict[str, list[str]] = {}

    if not CLAUDE_PROJECTS_DIR.exists():
        return projects

    for jsonl in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        if "/tasks/" in str(jsonl):
            continue
        mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
        if not (start_dt <= mtime < end_dt):
            continue

        # Extract project name from path
        # Directory names look like: -Users-cdiseetheeye-Desktop-AILawfirm
        rel = jsonl.relative_to(CLAUDE_PROJECTS_DIR)
        parts = list(rel.parts)
        raw_name = parts[0] if parts else "unknown"
        # Strip the home/Desktop prefix pattern, keep the last meaningful segment
        segments = raw_name.split("-")
        skip = {"Users", "cdiseetheeye", "Desktop", "Documents", ""}
        meaningful = [s for s in segments if s not in skip]
        project_name = "-".join(meaningful) if meaningful else "misc"
        # If still looks like a path artifact, use the JSONL filename
        if not project_name or project_name.strip("-") == "":
            project_name = jsonl.stem[:30] or "misc"

        messages = []
        try:
            with open(jsonl, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "user":
                            content = obj.get("message", {}).get("content", [])
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "").strip()
                                    if text and len(text) > 5:
                                        messages.append(text[:500])
                                elif isinstance(block, str) and len(block) > 5:
                                    messages.append(block[:500])
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read {jsonl}: {e}")
            continue

        if messages:
            if project_name not in projects:
                projects[project_name] = []
            projects[project_name].extend(messages)

    return projects


# ──────────────────────────────────────────────
# Briefing Document
# ──────────────────────────────────────────────
def build_briefing(
    start: date,
    end: date,
    recordings: list[dict],
    summaries: dict[str, str],
    sessions: dict[str, list[str]],
) -> str:
    """Build the integrated briefing document."""
    total_mins = sum(r.get("duration", 0) for r in recordings) / 60000
    total_hours = total_mins / 60

    lines = [
        f"# 최동인 일주일 종합 브리핑 ({start.strftime('%Y.%m.%d')}~{end.strftime('%m.%d')})",
        "",
        "## 인물 프로필",
        PROFILE,
        "",
        "---",
        "",
        f"## Plaud 녹음 요약 ({len(recordings)}건, 약 {total_hours:.1f}시간)",
        "",
    ]

    # Group recordings by date
    by_date: dict[str, list[dict]] = {}
    for r in recordings:
        dt = datetime.fromtimestamp(r.get("start_time", 0) / 1000, tz=TZ)
        date_key = dt.strftime("%m/%d (%a)")
        by_date.setdefault(date_key, []).append(r)

    for date_key, recs in by_date.items():
        lines.append(f"### {date_key}")
        for r in recs:
            dt = datetime.fromtimestamp(r.get("start_time", 0) / 1000, tz=TZ)
            dur_min = r.get("duration", 0) // 60000
            name = r.get("filename", "녹음")
            rid = str(r.get("id", ""))
            summary = summaries.get(rid, "")
            lines.append(f"- **{name}** ({dur_min}분, {dt.strftime('%H:%M')})")
            if summary:
                # Truncate to first 500 chars for briefing
                short = summary[:800].replace("\n", " ").strip()
                lines.append(f"  - {short}")
        lines.append("")

    lines.extend([
        "---",
        "",
        f"## Claude Code 작업 내역 ({sum(len(v) for v in sessions.values())}개 메시지, {len(sessions)}개 프로젝트)",
        "",
    ])

    for project, msgs in sessions.items():
        lines.append(f"### {project} ({len(msgs)}개 메시지)")
        for msg in msgs[:10]:  # Top 10 messages per project
            short = msg[:200].replace("\n", " ").strip()
            lines.append(f"- {short}")
        if len(msgs) > 10:
            lines.append(f"- ... 외 {len(msgs) - 10}개")
        lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Claude API Analysis
# ──────────────────────────────────────────────
async def run_analysis(briefing: str) -> list[tuple[str, str]]:
    """Run 10 analyst perspectives via Claude API concurrently."""
    client = anthropic.AsyncAnthropic()

    async def analyze(role: str, perspective: str, question: str) -> tuple[str, str]:
        prompt = f"""당신은 {role}입니다. 아래 주간 브리핑을 {perspective} 관점에서 심층 분석하세요.

핵심 질문: "{question}"

분석에 반드시 포함할 섹션:
1. 핵심 진단 (3줄 요약)
2. 상세 분석 (데이터 기반, 구체적 수치 인용)
3. Undefined Guardrails (미정의된 가드레일)
4. Unvalidated Assumptions (검증되지 않은 가정)
5. Recommendations (우선순위 정렬, 최대 5개)
6. Open Questions

한국어로 작성.

---

{briefing}"""

        resp = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        return role, text

    tasks = [analyze(r, p, q) for r, p, q in ANALYST_ROLES]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"Analysis failed: {r}")
            output.append(("Error", str(r)))
        else:
            output.append(r)
    return output


# ──────────────────────────────────────────────
# Synthesis
# ──────────────────────────────────────────────
async def synthesize(briefing: str, analyses: list[tuple[str, str]]) -> str:
    """Generate final synthesis from all analyses."""
    combined = "\n\n---\n\n".join(
        f"## {role}\n{text}" for role, text in analyses if role != "Error"
    )

    client = anthropic.AsyncAnthropic()
    resp = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": f"""아래 10인 분석가의 주간 분석 결과를 종합하여 다음 구조로 정리하세요:

1. **한줄 요약**: 전원이 공통으로 지적한 핵심 메시지
2. **전원 일치 진단**: 모든 분석가가 동의한 결론
3. **각 에이전트 핵심 한줄 요약** (표)
4. **이번 주 가장 잘한 3가지** (근거 에이전트 명시)
5. **이번 주 가장 위험한 3가지** (근거 에이전트 명시)
6. **다음 주 긴급 액션 TOP 5** (우선순위, 액션, 근거 표)

한국어로 작성. 간결하되 구체적으로.

---

{combined}"""}],
    )
    return resp.content[0].text if resp.content else ""


# ──────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────
def build_output(
    start: date,
    end: date,
    recordings: list[dict],
    sessions: dict[str, list[str]],
    synthesis: str,
    analyses: list[tuple[str, str]],
    briefing: str,
) -> str:
    """Build final Obsidian markdown output."""
    week_label = iso_week_label(end)
    total_hours = sum(r.get("duration", 0) for r in recordings) / 3600000
    num_sessions = sum(len(v) for v in sessions.values())

    lines = [
        "---",
        "type: weekly-retrospective",
        f"week: {week_label}",
        f'period: {start.strftime("%Y.%m.%d")} ~ {end.strftime("%m.%d")}',
        f"plaud_count: {len(recordings)}",
        f"plaud_hours: {total_hours:.1f}",
        f"claude_sessions: {num_sessions}",
        f"projects: {len(sessions)}",
        f'created: {datetime.now(TZ).strftime("%Y-%m-%d %H:%M")}',
        "---",
        "",
        f'# 주간회고 — {start.strftime("%Y년 %m월")} {end.isocalendar().week}주차',
        "",
        synthesis,
        "",
        "---",
        "",
        "## 상세 분석",
        "",
    ]

    for role, text in analyses:
        if role != "Error":
            lines.extend([f"### {role}", "", text, "", "---", ""])

    lines.extend(["## 원본 브리핑 데이터", "", briefing])

    return "\n".join(lines)


def save_to_obsidian(content: str, end: date) -> Path:
    """Save the review to Obsidian vault."""
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    week_label = iso_week_label(end)
    filename = f"{week_label}-주간회고.md"
    path = WEEKLY_DIR / filename

    # Version suffix if exists
    if path.exists():
        v = 2
        while True:
            filename = f"{week_label}-주간회고_v{v}.md"
            path = WEEKLY_DIR / filename
            if not path.exists():
                break
            v += 1

    path.write_text(content, encoding="utf-8")
    logger.info(f"Saved to {path}")
    return path


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="주간회고 자동화")
    parser.add_argument("--start", help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", help="종료일 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="파일 저장 없이 미리보기")
    parser.add_argument("--skip-plaud", action="store_true", help="Plaud 수집 건너뛰기")
    parser.add_argument("--skip-analysis", action="store_true", help="AI 분석 건너뛰기")
    args = parser.parse_args()

    start, end = get_date_range(args.start, args.end)
    logger.info(f"Review period: {start} ~ {end}")

    # Phase 1: Collect data
    recordings = []
    summaries: dict[str, str] = {}

    if not args.skip_plaud:
        token = get_plaud_token()
        if token:
            async with httpx.AsyncClient(timeout=30) as client:
                recordings = await fetch_plaud_recordings(client, token, start, end)
                # Fetch summaries for recordings > 10 min
                for r in recordings:
                    if r.get("duration", 0) > 600000:  # > 10 min
                        rid = str(r.get("id", ""))
                        summary = await fetch_plaud_summary(client, token, rid)
                        if summary:
                            summaries[rid] = summary
                            logger.info(f"  Summary for {r.get('filename', rid)}")
        else:
            logger.warning("No Plaud token found, skipping Plaud data")

    sessions = collect_claude_sessions(start, end)
    logger.info(f"Claude Code: {len(sessions)} projects, {sum(len(v) for v in sessions.values())} messages")

    # Phase 2: Build briefing
    briefing = build_briefing(start, end, recordings, summaries, sessions)
    logger.info(f"Briefing: {len(briefing)} chars")

    if args.skip_analysis:
        logger.info("Skipping analysis (--skip-analysis)")
        if not args.dry_run:
            path = save_to_obsidian(briefing, end)
            print(f"Saved briefing (no analysis) to: {path}")
        else:
            print(briefing)
        return

    # Phase 3: 10-agent analysis
    logger.info("Running 10-agent analysis...")
    analyses = await run_analysis(briefing)
    logger.info(f"Completed {len(analyses)} analyses")

    # Phase 4: Synthesis
    logger.info("Synthesizing...")
    synthesis = await synthesize(briefing, analyses)

    # Phase 5: Output
    output = build_output(start, end, recordings, sessions, synthesis, analyses, briefing)

    if args.dry_run:
        print(output)
    else:
        path = save_to_obsidian(output, end)
        print(f"Saved to: {path}")


if __name__ == "__main__":
    asyncio.run(main())
