# Onlime v2: AI Second Brain 시스템 아키텍처

> 최동인의 로컬 PC 활동을 자동 수집하여 Obsidian Second Brain을 구축하는 AI 시스템
> 작성일: 2026-03-18 | 10-Agent Deep Research 기반

---

## 1. 기존 Onlime v1 비판적 분석

### 잘 된 것 (유지)
- **Atomic file writes**: tmpfile → rename 패턴으로 Obsidian이 반쯤 쓴 파일을 읽는 문제 방지
- **MD5 해시 기반 중복 방지**: kmsg에 안정적 ID가 없는 상황에서 합리적인 선택
- **Standalone 실행 가능**: 각 모듈을 `tsx`로 독립 실행 가능

### 근본적 문제점

| 문제 | 심각도 | 설명 |
|------|--------|------|
| **데일리 노트 = 데이터 저장소** | P0 | 원본 메시지를 데일리 노트에 직접 덤프. 노트가 비대해지고, 토픽별 검색/링크 불가능 |
| **State/Write 레이스 컨디션** | P0 | `appendToDaily()` 성공 후 `saveState()` 실패 시 메시지 중복. 역순이면 유실 |
| **단일 소스** | P1 | 카카오톡만 지원. 이메일, 캘린더, 슬랙, 회의록, PC 활동 미지원 |
| **Markdown 수술 취약성** | P1 | 문자열 인덱스로 섹션 찾아 삽입. 사용자 편집 시 파일 손상 위험 |
| **OpenClaw 의존성 불안정** | P1 | `openclaw run --no-interactive` 비표준 명령, `/api/chat` 비존재 엔드포인트 |
| **프로세스 관리 부재** | P1 | LaunchAgent 미설정, 리부트 시 자동 복구 불가 |
| **양방향 상호작용 없음** | P2 | Obsidian 기존 지식을 활용한 컨텍스트 제공 불가 |

### 핵심 교훈
> **데일리 노트는 데이터 저장소가 아니라 대시보드여야 한다.**
> 원본 데이터 → 개별 소스 노트 → 데일리 노트는 Dataview 쿼리로 연결만.

---

## 2. 시스템 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    macOS LaunchAgent                         │
│              com.onlime.daemon.plist                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                 Node.js Daemon (단일 프로세스)                │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Collectors (수집 계층)                    │    │
│  │  ┌────────┐┌───────┐┌──────┐┌──────┐┌──────┐┌────┐ │    │
│  │  │카카오톡 ││ Gmail ││ GCal ││Slack ││Plaud ││ PC │ │    │
│  │  │ 5min   ││ 5min  ││15min ││ 5min ││watch ││1min│ │    │
│  │  └───┬────┘└───┬───┘└──┬───┘└──┬───┘└──┬───┘└─┬──┘ │    │
│  └──────┼─────────┼───────┼───────┼───────┼──────┼─────┘    │
│         │         │       │       │       │      │           │
│  ┌──────▼─────────▼───────▼───────▼───────▼──────▼─────┐    │
│  │           SQLite Event Queue (WAL 모드)               │    │
│  │  events | sync_cursors | processed | people | health  │    │
│  └──────────────────────┬────────────────────────────────┘    │
│                         │                                     │
│  ┌──────────────────────▼────────────────────────────────┐    │
│  │              Pipeline Processor                        │    │
│  │  Normalize → Enrich (Rules+AI) → Route → Write        │    │
│  └──────────────────────┬────────────────────────────────┘    │
│                         │                                     │
│  ┌──────────────────────▼────────────────────────────────┐    │
│  │              Obsidian Writer                            │    │
│  │  Atomic writes → /Users/aiparty/Desktop/Obsidian_sinc/ │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐    │
│  │   Scheduled Jobs                                       │    │
│  │   08:00 Morning Briefing (claude -p)                   │    │
│  │   23:00 Daily Summary (Anthropic API)                  │    │
│  │   Sun 22:00 Weekly Review                              │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 4-Layer 지식 계층 구조

기존 v1의 "모든 것을 데일리 노트에 덤프" 대신, Progressive Summarization 기반 계층 구조 도입:

```
Layer 0: RAW DATA (사용자에게 보이지 않음)
  └─ ~/.onlime/data/ — 원본 API 응답, 전체 로그
  └─ SQLite events 테이블의 raw 컬럼
  └─ 30일 후 자동 삭제

Layer 1: SOURCE NOTES (자동 생성, status: raw)
  └─ 1. INPUT/Chat/     — 카카오톡/슬랙 대화별 노트
  └─ 1. INPUT/Email/    — 이메일 스레드별 노트
  └─ 1. INPUT/Calendar/ — 캘린더 이벤트별 노트
  └─ 1. INPUT/Meeting/  — 회의록 (Plaud 연동)
  └─ 사람/프로젝트 [[위키링크]] 포함

Layer 2: INSIGHTS (AI 추출, status: processed)
  └─ 2. OUTPUT/Insights/ — 의사결정, 합의사항, 핵심 아이디어
  └─ 2. OUTPUT/Actions/  — 추출된 액션 아이템
  └─ AI confidence가 높을 때만 생성

Layer 3: PERMANENT (인간 검토, status: reviewed)
  └─ 잡서 섹션의 자유 기술
  └─ 사용자가 Layer 2를 검토 후 승격
  └─ 진짜 "세컨드 브레인"
```

### 데일리 노트 = 대시보드 (데이터 저장 X)

```markdown
---
created: {{date}} {{time}}
type: daily
author: "[[🙍‍♂️최동인]]"
index: "[[MOC Daily Notes]]"
---
#### [[{{yesterday}} |◀︎]] {{date}} [[{{tomorrow}} |▶︎]]
---
## ==잡서


---
## 오늘의 기록
```dataview
TABLE WITHOUT ID file.link AS "노트", type AS "유형", source AS "출처"
FROM "" WHERE file.cday = date({{date}}) AND type != "daily"
SORT created ASC
```

## 카카오톡
```dataview
LIST FROM "1. INPUT/Chat"
WHERE file.cday = date({{date}}) AND source = "kakao"
```

## 이메일
```dataview
LIST FROM "1. INPUT/Email"
WHERE file.cday = date({{date}})
```

## 일정
```dataview
LIST FROM "1. INPUT/Calendar"
WHERE file.cday = date({{date}})
```

## 회의록
```dataview
LIST FROM "1. INPUT/Meeting"
WHERE file.cday = date({{date}})
```

## 액션 아이템
```dataview
TASK FROM "2. OUTPUT/Actions"
WHERE !completed AND file.cday = date({{date}})
```

---
## 리뷰
> _23:00 AI 요약 자동 삽입_

---
#### 생성
```dataview
list from "" where file.cday = date({{date}}) AND type != "daily"
```
#### 변형
```dataview
list from ""
where file.mday = date({{date}}) AND type != "daily" AND file.cday != date({{date}})
```
```

---

## 4. 통합 이벤트 스키마

```typescript
// src/types.ts — 모든 소스에서 공유하는 통합 스키마

interface OnlimeEvent {
  id: string;                    // UUID
  source: Source;
  sourceId: string;              // 소스별 고유 ID
  type: EventType;

  // 시간
  timestamp: string;             // ISO 8601
  duration?: number;             // 초 (회의/통화용)

  // 사람
  participants: Person[];
  author?: string;

  // 내용
  title?: string;
  body: string;
  summary?: string;              // AI 생성 요약

  // 분류
  project?: string;              // [[프로젝트명]]
  tags: string[];
  category?: 'decision' | 'action_item' | 'info' | 'question' | 'social';
  importance?: 'high' | 'medium' | 'low';

  // 연결
  relatedEvents: string[];
  obsidianLinks: string[];       // 생성할 [[위키링크]] 목록

  // 메타
  raw: unknown;                  // 원본 소스 데이터
  status: 'pending' | 'processing' | 'enriched' | 'written' | 'failed';
  enrichedAt?: string;
  writtenAt?: string;
  obsidianPath?: string;
}

type Source = 'kakao' | 'gmail' | 'gcal' | 'slack' | 'plaud' | 'pc' | 'web';
type EventType = 'message' | 'email' | 'calendar_event' | 'transcript' | 'activity' | 'bookmark';

interface Person {
  name: string;
  wikilink: string;              // [[🙍‍♂️이름_설명]]
  aliases: string[];
  email?: string;
  source: string;
}
```

---

## 5. SQLite 스키마 (상태 관리의 단일 진실)

```sql
-- ~/.onlime/onlime.db (WAL 모드)

CREATE TABLE events (
  id TEXT PRIMARY KEY,           -- UUID
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  type TEXT NOT NULL,
  payload TEXT NOT NULL,         -- JSON (OnlimeEvent)
  status TEXT DEFAULT 'pending',
  created_at TEXT NOT NULL,
  processed_at TEXT,
  written_at TEXT,
  obsidian_path TEXT,
  error TEXT,
  retry_count INTEGER DEFAULT 0,
  UNIQUE(source, source_id)      -- 소스별 중복 방지
);

CREATE TABLE sync_cursors (
  source TEXT PRIMARY KEY,
  cursor_value TEXT,             -- 소스별: message hash, historyId, timestamp
  updated_at TEXT NOT NULL
);

CREATE TABLE people (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  wikilink TEXT NOT NULL,        -- [[🙍‍♂️이름_설명]]
  aliases TEXT,                  -- JSON array
  emails TEXT,                   -- JSON array
  slack_id TEXT,
  kakao_name TEXT,
  updated_at TEXT
);

CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  wikilink TEXT NOT NULL,        -- [[프로젝트명]]
  keywords TEXT,                 -- JSON array (자동 매칭용)
  active INTEGER DEFAULT 1,
  updated_at TEXT
);

CREATE TABLE health_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  status TEXT NOT NULL,          -- 'ok' | 'warning' | 'error'
  message TEXT,
  events_count INTEGER DEFAULT 0,
  checked_at TEXT NOT NULL
);

CREATE INDEX idx_events_status ON events(status);
CREATE INDEX idx_events_source ON events(source, created_at);
```

**v1 state.json 대비 개선점:**
- 트랜잭션으로 write/state 업데이트를 원자적으로 처리 (레이스 컨디션 해결)
- 실패한 이벤트 쿼리 가능 (디버깅)
- 재시도 카운트로 무한 루프 방지
- `UNIQUE(source, source_id)`로 멱등성 보장

---

## 6. 소스별 Collector 설계

### 6.1 카카오톡 (기존 개선)

| 항목 | v1 | v2 |
|------|-----|-----|
| 도구 | kmsg CLI | kmsg CLI (동일) |
| 주기 | 5분 | 5분 (동일) |
| 상태 추적 | JSON 파일 MD5 해시 | SQLite sync_cursors |
| 출력 | 데일리 노트에 원본 덤프 | `1. INPUT/Chat/YYYYMMDD_채팅방_Chat.md` 개별 노트 |
| 중복 방지 | 프로세스 메모리 + JSON | SQLite UNIQUE 제약 |

**개별 채팅 노트 형식:**
```markdown
---
created: 2026-03-18 14:30
type: chat-log
source: kakao
chat_room: "테크노크라츠 유민승"
participants:
  - "[[🙍‍♂️유민승]]"
status: raw
---
# 테크노크라츠 유민승 — 2026-03-18

- **14:05** 유민승: 내일 미팅 가능하신가요?
- **14:07** 최동인: 네, 14시 어떠세요?
- **14:08** 유민승: 좋습니다. 강남역 카페에서 뵙겠습니다.
```

### 6.2 Gmail

| 항목 | 설계 |
|------|------|
| 도구 | Gmail MCP 서버 (이미 연결됨) |
| 주기 | 5분 (카카오톡과 1분 오프셋) |
| 필터 | noreply 제외, promotions/social 제외, 보안코드 제외 |
| 상태 추적 | historyId 기반 |
| 출력 | `1. INPUT/Email/YYYYMMDD_발신자_제목_Email.md` |

**필터 우선순위:**
1. SKIP: `noreply|no-reply` 발신자 AND 알려진 연락처 아님
2. SKIP: `category:promotions` OR `category:social`
3. SKIP: 보안코드/로그인 관련 (`보안 코드|security code|로그인`)
4. CAPTURE: `is:starred`
5. CAPTURE: 연락처 화이트리스트 발신자
6. CAPTURE: `category:personal` AND 실제 사람
7. MAYBE: AI 분류 (중요도 5+/10이면 캡처)

### 6.3 Google Calendar

| 항목 | 설계 |
|------|------|
| 도구 | Google Calendar MCP 서버 (이미 연결됨) |
| 주기 | 15분 |
| 출력 | `1. INPUT/Calendar/YYYYMMDD_이벤트명_Event.md` |
| 추가 기능 | 미팅 전 브리프 (60분 전), 미팅 후 스켈레톤 (15분 후) |

**Pre-Meeting Brief 자동 생성 (핵심 가치 기능):**
- 이벤트 시작 60분 전에 트리거
- 참석자 → Obsidian People 노트 검색 → 최근 대화/미팅 이력 수집
- AI로 브리프 생성 → `1. INPUT/Meeting/` 에 저장

**연락처 매핑:** `config/contacts.json`으로 이메일 → `[[위키링크]]` 매핑

### 6.4 Slack

| 항목 | 설계 |
|------|------|
| 도구 | `@modelcontextprotocol/server-slack` 또는 `korotovsky/slack-mcp-server` |
| 주기 | 5분 (카카오톡과 2분 오프셋) |
| 필터 | 채널 화이트리스트, DM/멘션 우선 |
| 출력 | `1. INPUT/Chat/YYYYMMDD_채널명_Slack.md` |

**주의사항:**
- 2026-03-03부터 비마켓플레이스 앱은 `conversations.history` 분당 1회 제한
- 소유하지 않은 워크스페이스: 요약만 저장 (원본 메시지 X), 관리자 승인 권장
- bot 메시지 (GitHub/Jira 알림)는 중복 방지 위해 별도 처리

### 6.5 Plaud Note AI

| 항목 | 설계 |
|------|------|
| 도구 | Plaud Developer API 또는 `plaud-sync-for-obsidian` 플러그인 |
| 트리거 | `chokidar`로 Plaud 동기화 폴더 감시 (파일 생성 이벤트) |
| 출력 | `1. INPUT/Meeting/YYYYMMDD_참석자_제목_Meeting.md` (기존 형식 유지) |

**캘린더 연동:**
- Plaud 녹음 시작/종료 시간 ↔ Google Calendar 이벤트 시간 겹침으로 매칭
- 매칭 성공 시 → 캘린더에서 자동 생성한 미팅 스켈레톤에 Plaud 내용 병합
- 매칭 실패 시 → 독립 회의록 노트 생성

**한국어 최적화:** Plaud 커스텀 어휘에 프로젝트명 등록 (더해커톤, 에이아이당, 테크노크라츠 등)

### 6.6 로컬 PC 활동

| 항목 | 설계 |
|------|------|
| 도구 | Option A: Screenpipe (권장) / Option B: DIY osascript + chokidar |
| 주기 | 앱 포커스 10초, 파일 이벤트 즉시, 브라우저 5분 |
| 출력 | 데일리 노트 `## 활동 요약`에 집계 데이터만 |

**Screenpipe 권장 이유:**
- 16,700+ GitHub 스타, MIT 라이선스
- 스크린 + 오디오 연속 캡처, OCR/Accessibility API 텍스트 추출
- Node.js SDK (`@screenpipe/js`), REST API (localhost:3030), MCP 서버
- 커스텀 "pipe" 플러그인으로 Obsidian 연동 가능

**프라이버시 필터:** 패스워드 매니저, 은행 앱, 프라이빗 브라우징 자동 제외

---

## 7. AI 처리 파이프라인

### 3-Tier AI 전략

```
Tier 1: 규칙 기반 (비용 $0, 즉시)
  ├─ 날짜/시간 추출 (정규식)
  ├─ 알려진 사람 매칭 (people DB 룩업)
  ├─ 프로젝트 키워드 매칭 (projects DB)
  ├─ URL/전화번호/이메일 추출 (정규식)
  └─ 한국어 이름 감지 (한글 패턴)

Tier 2: 저비용 AI (빠르고 저렴)
  ├─ 메시지 분류 (질문/결정/액션/정보)
  ├─ 중요도 판단
  └─ 모델: Haiku 또는 DeepSeek ($0.70/1M tokens)

Tier 3: 고품질 AI (비싸지만 정확)
  ├─ 일일 종합 요약 (23:00)
  ├─ 미팅 트랜스크립트 분석
  ├─ 주간/월간 리뷰 생성
  ├─ Pre-Meeting Brief 생성
  └─ 모델: Anthropic API (Sonnet/Opus)
```

**비용 추정 (월간):**
- 일상 처리 (Tier 2): ~$1.50/월
- 요약/분석 (Tier 3): ~$3.00/월
- **총 예상: < $5/월**

**핵심 원칙: AI는 선택적 보강, 필수 경로가 아님**
- AI 실패 시 → enrichment 없이 원본 데이터로 Obsidian에 기록
- AI 없어도 시스템은 동작 (캡처 + 정리는 규칙 기반)
- AI가 더 좋게 만들어줄 뿐

### OpenClaw → Anthropic API 직접 호출로 전환

**이유:**
- OpenClaw `run --no-interactive`는 비표준 명령
- `http://127.0.0.1:18789/api/chat`는 존재하지 않는 엔드포인트
- OpenClaw Gateway는 WebSocket 기반이며 HTTP REST는 2차적
- Anthropic API 직접 호출이 결정적(deterministic)이고 안정적

**OpenClaw의 역할 재정의:**
- 메시징 채널 브릿지 (카카오톡 명령 수신/알림 발송) → 유지
- AI 요약/분석 → Anthropic API로 교체

---

## 8. Claude Code 통합 전략

### Claude Code = 개발 도구 + 스케줄 오케스트레이터 (런타임 데몬 X)

```
┌─────────────────────────────────────────────┐
│           항상 실행 (24/7)                    │
│  Onlime Node.js Daemon                       │
│  - 데이터 수집 (polling/watching)             │
│  - SQLite 이벤트 큐                           │
│  - 규칙 기반 처리 (Tier 1)                    │
│  - Obsidian 파일 쓰기                         │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│           스케줄 실행 (cron)                   │
│  claude -p (Headless Mode)                   │
│  - 08:00 Morning Briefing                    │
│  - 23:00 Daily Summary                       │
│  - Pre-Meeting Briefs (이벤트 전 60분)        │
│  - 주간 리뷰 (일요일)                         │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│           대화형 (사용자 요청 시)               │
│  Claude Code Interactive                     │
│  - MCP 서버로 Gmail/Calendar 접근             │
│  - Obsidian 볼트 읽기/쓰기                    │
│  - 시스템 코드 개발/디버깅                     │
│  - Hooks로 활동 로깅                          │
└─────────────────────────────────────────────┘
```

### Hooks 활용

```json
// ~/.claude/settings.json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__claude_ai_Gmail__*",
        "hooks": [{
          "type": "command",
          "command": "echo '{\"time\":\"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'\",\"tool\":\"gmail\"}' >> ~/.onlime/logs/claude-activity.jsonl"
        }]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "echo 'Claude session ended' >> ~/.onlime/logs/claude-activity.jsonl"
        }]
      }
    ]
  }
}
```

### 스케줄 작업 (crontab)

```bash
# Morning Briefing
0 8 * * * cd /Users/aiparty/Desktop/Onlime && claude -p "오늘의 Gmail 수신함과 Google Calendar 일정을 확인하고, Obsidian 데일리 노트에 모닝 브리핑을 작성해줘" --allowedTools "mcp__claude_ai_Gmail__*,mcp__claude_ai_Google_Calendar__*,Write,Read" >> ~/.onlime/logs/morning.log 2>&1

# Pre-Meeting Brief (매 30분마다 확인)
*/30 * * * * cd /Users/aiparty/Desktop/Onlime && node dist/pre-meeting-check.js >> ~/.onlime/logs/pre-meeting.log 2>&1

# Daily Summary
0 23 * * * cd /Users/aiparty/Desktop/Onlime && node dist/daily-summary.js >> ~/.onlime/logs/summary.log 2>&1

# Weekly Review
0 22 * * 0 cd /Users/aiparty/Desktop/Onlime && claude -p "이번 주 Obsidian 데일리 노트들을 분석해서 주간 리뷰를 생성해줘" --allowedTools "Read,Write,Glob" >> ~/.onlime/logs/weekly.log 2>&1
```

---

## 9. Obsidian 볼트 구조 (개편안)

```
Obsidian_sinc/
├── 1. INPUT/
│   ├── Article/          (기존 유지)
│   ├── Book/             (기존 유지)
│   ├── Calendar/         ← NEW: 캘린더 이벤트 노트
│   ├── Chat/             ← NEW: 카카오톡/슬랙 대화별 노트
│   ├── Class/            (기존 유지)
│   ├── Email/            ← NEW: 이메일 스레드별 노트
│   ├── Inbox/            (기존 유지 — 수동 캡처용)
│   ├── Media/            (기존 유지)
│   ├── Meeting/          (기존 유지 — Plaud + 캘린더 연동)
│   ├── People/           (기존 유지)
│   ├── Quote/            (기존 유지)
│   └── Term/             (기존 유지)
├── 2. OUTPUT/
│   ├── Actions/          ← NEW: 추출된 액션 아이템
│   ├── Daily/            (기존 유지 — 대시보드로 전환)
│   ├── Insights/         ← NEW: AI 추출 인사이트
│   └── MOC*.md           (기존 유지 — Dataview 기반으로 개선)
├── Archive/              (기존 유지)
└── System/
    ├── Templates/        (기존 유지 — 새 템플릿 추가)
    └── MOC/              (기존 유지)
```

### 통합 Frontmatter 스키마

```yaml
---
created: 2026-03-18 14:30           # 필수
type: chat-log | email | event | meeting | insight | action | daily | person
source: kakao | gmail | gcal | slack | plaud | pc | web | manual
author: "[[🙍‍♂️최동인]]"
participants:                        # 다중 참여자
  - "[[🙍‍♂️유민승]]"
project: "[[에이아이당 AIPARTY]]"     # 관련 프로젝트
tags: [auto-generated]
status: raw | processed | reviewed   # 지식 성숙도
confidence: high | medium | low      # AI 추출 신뢰도
index: "[[MOC Name]]"
---
```

---

## 10. 프로젝트 구조 (코드)

```
Onlime/
├── src/
│   ├── index.ts                 # 데몬 진입점 + 스케줄러
│   ├── db.ts                    # SQLite 초기화 + 헬퍼
│   ├── types.ts                 # OnlimeEvent, Person 등 통합 타입
│   │
│   ├── collectors/              # 소스별 수집기
│   │   ├── kakao.ts             # 기존 kakao-monitor 리팩터
│   │   ├── gmail.ts
│   │   ├── gcal.ts
│   │   ├── slack.ts
│   │   ├── plaud.ts
│   │   └── activity.ts          # PC 활동 (Screenpipe 연동)
│   │
│   ├── pipeline/                # 처리 파이프라인
│   │   ├── normalizer.ts        # 소스별 → OnlimeEvent 변환
│   │   ├── enricher.ts          # Rules + AI 보강
│   │   ├── router.ts            # 어디에 쓸지 결정
│   │   └── processor.ts         # 파이프라인 오케스트레이터
│   │
│   ├── writers/                 # Obsidian 쓰기
│   │   ├── obsidian.ts          # 공통 쓰기 로직 (atomic write)
│   │   ├── daily-note.ts        # 데일리 노트 대시보드
│   │   ├── source-note.ts       # 소스별 개별 노트
│   │   └── templates.ts         # 노트 타입별 템플릿
│   │
│   ├── ai/                      # AI 처리
│   │   ├── anthropic.ts         # Anthropic API 클라이언트
│   │   ├── summarizer.ts        # 일일/주간 요약
│   │   ├── extractor.ts         # 엔티티/액션 추출
│   │   └── classifier.ts        # 중요도/분류
│   │
│   └── utils/
│       ├── people.ts            # 사람 매칭 로직
│       ├── projects.ts          # 프로젝트 매칭
│       ├── health.ts            # 헬스 모니터링
│       └── privacy.ts           # 프라이버시 필터
│
├── config/
│   ├── contacts.json            # 이메일/슬랙ID → 위키링크 매핑
│   ├── projects.json            # 프로젝트 키워드 매핑
│   ├── sources.json             # 소스별 설정 (주기, 필터 등)
│   └── privacy.json             # 제외 앱/패턴 목록
│
├── scripts/
│   ├── pre-meeting-check.ts     # Pre-Meeting Brief 트리거
│   ├── daily-summary.ts         # 일일 요약 (23:00)
│   └── weekly-review.ts         # 주간 리뷰 (일요일)
│
├── com.onlime.daemon.plist      # macOS LaunchAgent
├── openclaw.json
├── package.json
└── tsconfig.json
```

---

## 11. 핵심 의존성

```json
{
  "dependencies": {
    "better-sqlite3": "^11.0.0",     // SQLite WAL 모드
    "node-cron": "^3.0.3",          // 스케줄링 (기존)
    "chokidar": "^4.0.0",           // Plaud 파일 감시
    "@anthropic-ai/sdk": "^1.0.0",  // AI 요약/분석 (OpenClaw 대체)
    "gray-matter": "^4.0.3",        // Frontmatter 파싱
    "uuid": "^10.0.0"               // 이벤트 ID 생성
  },
  "devDependencies": {
    "@types/better-sqlite3": "^7.6.0",
    "@types/node": "^22.0.0",
    "@types/node-cron": "^3.0.11",
    "tsx": "^4.19.0",
    "typescript": "^5.7.0"
  }
}
```

**제거:**
- OpenClaw CLI/API 의존성 → Anthropic API 직접 호출로 대체

**나중에 추가 (Phase 2+):**
- `@slack/web-api` — Slack 연동 시
- `@screenpipe/js` — PC 활동 모니터링 시
- `googleapis` — Gmail/Calendar API 직접 사용 시 (MCP 대안)

---

## 12. 구현 로드맵

### Phase 1: 기반 리팩터링 (1-2주)

- [ ] SQLite DB 스키마 + `db.ts` 구현
- [ ] `OnlimeEvent` 통합 타입 시스템
- [ ] `kakao.ts` 리팩터 (기존 kakao-monitor → SQLite 기반)
- [ ] `source-note.ts` — 데일리 노트 대신 개별 노트 생성
- [ ] `daily-note.ts` — Dataview 기반 대시보드 템플릿
- [ ] `anthropic.ts` — OpenClaw 대체 AI 클라이언트
- [ ] `com.onlime.daemon.plist` — LaunchAgent 설정
- [ ] 기존 v1과 동일한 기능이 새 아키텍처에서 동작 확인

### Phase 2: 멀티소스 확장 (2-3주)

- [ ] `gmail.ts` — Gmail MCP 기반 이메일 수집
- [ ] `gcal.ts` — Calendar MCP 기반 일정 수집
- [ ] `contacts.json` + `people.ts` — 연락처 매핑 시스템
- [ ] Pre-Meeting Brief 자동 생성
- [ ] Post-Meeting 스켈레톤 자동 생성
- [ ] `daily-summary.ts` — 멀티소스 일일 요약

### Phase 3: 심화 통합 (3-4주)

- [ ] Slack MCP 서버 설치 + `slack.ts`
- [ ] Plaud API 연동 + `plaud.ts` + 캘린더 매칭
- [ ] `enricher.ts` — AI 기반 엔티티/액션 추출
- [ ] `classifier.ts` — 이메일/메시지 중요도 분류
- [ ] 주간 리뷰 자동 생성

### Phase 4: 로컬 활동 + 고급 기능 (4-6주)

- [ ] Screenpipe 연동 또는 DIY 활동 모니터링
- [ ] 브라우저 히스토리 수집
- [ ] MOC 자동 생성/업데이트
- [ ] Claude Code Hooks 통합
- [ ] 헬스 대시보드 (localhost)

---

## 13. 핵심 설계 원칙 요약

| 원칙 | 설명 |
|------|------|
| **데일리 노트 = 대시보드** | 데이터 저장 X, Dataview 쿼리로 연결만 |
| **SQLite가 척추** | 큐, 상태, 커서, 사람, 프로젝트, 헬스 — 하나의 DB |
| **AI는 보강, 필수 아님** | AI 없어도 캡처+정리 동작. AI가 더 좋게 만듦 |
| **Atomic writes** | tmpfile → rename. Obsidian 볼트 손상 방지 |
| **멱등성** | 언제든 재시작 가능. UNIQUE 제약 + 커서 추적 |
| **단일 프로세스, 단일 DB** | 분산 시스템 NO. 개인 도구에 맞는 단순함 |
| **Progressive Summarization** | Raw → Source Note → Insight → Permanent |
| **Anthropic API 직접 호출** | OpenClaw Gateway 불안정성 해소 |
| **비용 < $5/월** | Tier별 AI 사용으로 비용 최적화 |
| **프라이버시 우선** | 비밀번호, 보안코드, 금융정보 자동 제외 |

---

## 부록 A: 기술 선택 근거

| 결정 | 선택 | 이유 |
|------|------|------|
| 언어 | TypeScript/Node.js | 기존 코드베이스, I/O 바운드에 적합, 풍부한 생태계 |
| DB | SQLite (WAL) | 단일 파일, ACID, 12K msg/sec, 쿼리 가능, 인프라 비용 $0 |
| AI | Anthropic API 직접 | 결정적, 안정적, OpenClaw Gateway 우회 |
| 스케줄 | node-cron + macOS cron | 데몬 내부: node-cron / AI 작업: system cron + `claude -p` |
| 파일 감시 | chokidar | 네이티브 FSEvents, 30M repos에서 사용 |
| 프로세스 관리 | LaunchAgent | macOS 네이티브, 리부트 자동 시작 |
| 활동 모니터링 | Screenpipe | 올인원, SDK 제공, MCP 서버, 16K+ 스타 |
| 메시지 큐 | SQLite events 테이블 | Redis/RabbitMQ는 개인 도구에 과잉. SQLite로 충분 |

## 부록 B: 리서치 소스 요약

10개 에이전트가 수집한 주요 참고 자료:
- Obsidian AI Second Brain 아키텍처 (NxCode, Remio, obsidian-claude-pkm)
- Claude Code MCP/Hooks/Agent SDK 공식 문서
- OpenClaw GitHub + 공식 문서 + 비교 분석
- Gmail/Calendar MCP 서버 + API 문서
- Slack MCP 서버 3종 비교 (Official, modelcontextprotocol, korotovsky)
- Plaud Developer Platform + SDK + Obsidian 플러그인
- macOS 활동 모니터링 (Screenpipe, ActivityWatch, AppleScript)
- 이벤트 파이프라인 아키텍처 (SQLite 큐, n8n/Temporal 비교)
- Progressive Summarization (Forte Labs)
- 한국어 맥락의 프라이버시/법적 고려사항
