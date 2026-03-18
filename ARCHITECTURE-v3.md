# Onlime v3: AI Second Brain — Final Architecture

> 최동인의 모든 업무 활동을 자동 수집하고, AI가 업무를 실행하며, Obsidian에 세컨드 브레인을 구축하는 시스템
> 작성일: 2026-03-18 | 10 Researchers + 5 Reviewers + User Feedback 종합

---

## 0. 설계 철학 — 세 가지 축

> "어떤 툴을 썼는지는 전혀 중요하지 않고, 어떤 사람과 어떤 일을 했는지가 중요함."
> — 최동인

모든 설계 결정은 이 **세 축**을 통해 판단한다:

```
1축: 시간 (When)  — 타임라인. 모든 이벤트는 언제 일어났는가.
2축: 사람 (Who)   — 관계. 누구와 상호작용했는가.
3축: 일 (What)    — 업무/프로젝트/섹터. 무엇을 했는가, 무엇을 해야 하는가.
─────────────────────────────────────────────────────────
메타데이터: 소스(카톡/이메일/슬랙), 도구, 포맷 → 전부 디테일
```

**사용자가 묻는 질문은 항상 이 패턴이다:**
- "**지난주**에 **유민승**과 **에이아이당** 관련 뭘 했지?" (시간×사람×일)
- "**오늘** 내가 해야 할 **일**이 뭐지?" (시간×일)
- "**유민승**과 최근 **무슨 이야기**를 했지?" (사람×일×시간)
- "**에이아이당** 프로젝트 진행 상황?" (일)

소스가 카톡이든 이메일이든 슬랙이든 — **전혀 중요하지 않다.**

---

## 1. v1/v2 비판 요약 및 v3에서의 해결

### 5명 리뷰어가 발견한 핵심 문제

| # | 문제 | 심각도 | v3 해결 |
|---|------|--------|---------|
| 1 | **SQLite vs .md 소스 오브 트루스 모순** | CRITICAL | .md가 진실, SQLite는 재구축 가능한 인덱스 |
| 2 | **MCP를 Node.js 데몬에서 호출 불가** | CRITICAL | googleapis 직접 사용 (MCP는 대화형 전용) |
| 3 | **소스 중심 폴더 구조** (도구별 분산) | MAJOR | 시간/사람/일 3축 네비게이션, 소스는 메타데이터 |
| 4 | **비용 과소 추정** ($5 vs $15-25) | MAJOR | 현실적 $15-20/월 명시, Tier별 최적화 |
| 5 | **보이지 않는 시스템** (UX 3.7/10) | MAJOR | macOS 알림 심박수(heartbeat) 필수 도입 |
| 6 | **OpenClaw 역할 혼재** | MAJOR | 메시징 브릿지 전용, AI 처리는 Anthropic API |
| 7 | **셀프 개선 루프 부재** | MAJOR | PAI 방식 피드백 루프 + 평점 시스템 도입 |
| 8 | **OpenClaw 요약기 완전 고장** | P0 | Anthropic SDK로 교체 (즉시) |
| 9 | **크로스소스 링킹 인프라 제로** | P0 | people.md 기반 매칭 시스템 구축 |
| 10 | **Dataview 성능** (20K+ 파일) | MAJOR | 스코프 쿼리 강제, 월별 아카이브 |

---

## 2. 시스템 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    macOS LaunchAgent                         │
│              com.onlime.daemon.plist                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              Onlime Node.js 데몬 (단일 프로세스)              │
│                                                              │
│  ┌─────────────── Collectors ──────────────────────┐        │
│  │ 카카오톡(kmsg) │ Gmail(googleapis) │ GCal(googleapis)│   │
│  │    5min        │      5min         │    15min        │   │
│  │ Plaud(chokidar)│                                     │   │
│  └──────────────────────┬──────────────────────────┘        │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────┐        │
│  │        .md 파일 쓰기 (Source of Truth)            │        │
│  │  1. INPUT/ 에 atomic write (tmp→rename)          │        │
│  └──────────────────────┬──────────────────────────┘        │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────┐        │
│  │        SQLite 인덱싱 (재구축 가능)                │        │
│  │  frontmatter 파싱 → events/people/projects 테이블 │        │
│  └──────────────────────┬──────────────────────────┘        │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────┐        │
│  │        Enricher (규칙 기반, 동기)                 │        │
│  │  사람 매칭 → [[위키링크]] 삽입                    │        │
│  │  프로젝트 키워드 매칭 → project frontmatter       │        │
│  │  .md 파일 업데이트 (in-place atomic write)       │        │
│  └─────────────────────────────────────────────────┘        │
│                                                              │
│  ┌─────────────── Heartbeat ───────────────────────┐        │
│  │ 매 수집 완료 시 macOS 알림:                       │        │
│  │ "카톡 12건, 이메일 3건 수집 완료"                  │        │
│  │ 실패 시: "⚠️ 카톡 수집 2시간째 실패"              │        │
│  └─────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│              스케줄 작업 (system crontab)                      │
│                                                              │
│  08:00  claude -p "Morning Brief"  → 데일리 노트             │
│  23:00  node daily-summary.js      → 데일리 노트 ## 리뷰     │
│  일요일  claude -p "Weekly Review"  → 주간 노트              │
│  매 30분 node pre-meeting-check.js → 미팅 브리프             │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│              OpenClaw (메시징 브릿지 전용)                     │
│                                                              │
│  인바운드: 카톡/슬랙에서 명령 수신 → 데몬에 전달              │
│  아웃바운드: 승인 후 kmsg send / Slack post                   │
│  Lobster: 멀티스텝 워크플로우 (승인 게이트 필수)              │
└──────────────────────────────────────────────────────────────┘
```

### v2 대비 핵심 변경

| v2 | v3 | 이유 |
|----|-----|------|
| MCP 서버로 Gmail/Calendar | **googleapis 직접 사용** | MCP는 Claude 세션 내에서만 동작. 데몬에서 호출 불가 (R5 발견) |
| SQLite = 소스 오브 트루스 | **.md = 소스 오브 트루스**, SQLite = 인덱스 | "File over App" 원칙. SQLite 삭제 후 rebuild 가능 (R1 해결) |
| 소스별 폴더 1급 | **소스 = 메타데이터**, 3축(시간/사람/일) 1급 | 사용자 피드백: 도구는 디테일 |
| AI enrichment 파이프라인 | **규칙 기반 enricher만 Phase 1** | 실현 가능성 4/10 → MVP 집중 (R2 권고) |
| Silent operation | **macOS 알림 heartbeat 필수** | UX #1 킬러: 보이지 않는 시스템 (R3 발견) |
| 비용 <$5/월 | **현실적 $15-20/월** | `claude -p` 오버헤드 포함 시 $5 불가능 (R1 계산) |
| 셀프 개선 없음 | **피드백 루프 + 평점 시스템** | PAI, Claudette 참고 (R4 권고) |

---

## 3. 3축 데이터 모델

### 핵심 원칙: 모든 이벤트는 시간×사람×일의 교차점이다

```typescript
interface OnlimeEvent {
  // === 3축 ===
  timestamp: string;             // 1축: 시간
  participants: string[];        // 2축: 사람 ([[위키링크]] 배열)
  project?: string;              // 3축: 일/프로젝트 ([[위키링크]])

  // === 메타데이터 (디테일) ===
  id: string;
  source: 'kakao' | 'gmail' | 'gcal' | 'slack' | 'plaud';
  source_id: string;
  title?: string;
  body: string;
  summary?: string;
  tags: string[];

  // === 연결 ===
  related: string[];             // 관련 이벤트 ID
  obsidian_path?: string;        // .md 파일 경로
}
```

### 3축 네비게이션

**시간축**: 데일리 노트 → 주간 리뷰 → 월간 리뷰 (타임라인 탐색)
**사람축**: People 노트 → "이 사람과의 모든 상호작용" (Dataview backlink)
**일축**: Project 노트 → "이 프로젝트의 모든 활동" (Dataview backlink)

어떤 축에서 시작하든, 나머지 두 축으로 자유롭게 이동 가능:
```
시간 → "오늘 유민승과 뭘 했지?" → 사람축으로 전환
사람 → "유민승과 에이아이당 관련?" → 일축으로 전환
일   → "에이아이당 이번 주 진행상황?" → 시간축으로 전환
```

---

## 4. Obsidian 볼트 구조

### 소스별이 아닌 기능별 폴더

```
Obsidian_sinc/
├── 1. INPUT/                    # 원본 데이터 (.md로 축적)
│   ├── 2026-03/                 # 월별 서브폴더 (볼륨 관리)
│   │   ├── 20260318_143000_테크노크라츠유민승_kakao.md
│   │   ├── 20260318_091500_더해커톤일정확인_gmail.md
│   │   ├── 20260318_140000_에이아이당주간회의_gcal.md
│   │   ├── 20260318_150000_유민승강남미팅_plaud.md
│   │   └── ...
│   ├── People/                  # 사람 노트 (2축 허브)
│   │   ├── 🙍‍♂️유민승.md
│   │   ├── 🙍‍♂️김소희.md
│   │   └── ...
│   ├── Article/                 # (기존 유지)
│   ├── Book/                    # (기존 유지)
│   ├── Meeting/                 # Plaud 트랜스크립트 (기존 유지)
│   └── ...
├── 2. OUTPUT/
│   ├── Daily/                   # 데일리 노트 (3축 대시보드)
│   ├── Weekly/                  # 주간 리뷰
│   ├── Monthly/                 # 월간 리뷰
│   └── Projects/                # 프로젝트 노트 (3축 허브)
│       ├── 에이아이당.md
│       ├── 더해커톤.md
│       ├── 테크노크라츠.md
│       └── ...
├── Archive/                     # 연간 아카이브 (Dataview 제외)
│   └── 2025/
└── System/                      # 템플릿, MOC
```

### 왜 소스별 하위폴더를 없앴는가

v2에서는 `Chat/`, `Email/`, `Calendar/` 폴더가 있었다. v3에서는 **월별 폴더 하나**에 모든 소스의 이벤트를 시간순으로 축적한다.

**이유:**
1. "카톡에서 온 건지 이메일에서 온 건지"는 디테일. 파일명의 `_kakao`, `_gmail` 접미사로 충분
2. 하나의 폴더에서 시간순 정렬하면 "오늘 뭐가 있었나" 한눈에 파악
3. Dataview 쿼리가 `FROM "1. INPUT/2026-03"` 하나로 통일 (폴더 4개 탐색 불필요)
4. 사람/프로젝트 검색은 frontmatter `participants`/`project` 필드로 (폴더 구조와 무관)

### 파일명 컨벤션

```
YYYYMMDD_HHMMSS_핵심키워드_source.md
```

예시:
- `20260318_143000_테크노크라츠유민승_kakao.md`
- `20260318_091500_더해커톤일정확인_gmail.md`
- `20260318_140000_에이아이당주간회의_gcal.md`

시간 정렬, 눈으로 스캔 가능, 소스 식별 가능, 유일성 보장.

---

## 5. 통합 Frontmatter 스키마 (3축 중심)

```yaml
---
# === 3축 (1급 시민) ===
date: 2026-03-18                           # 1축: 시간
participants:                               # 2축: 사람
  - "[[🙍‍♂️유민승]]"
project: "[[에이아이당]]"                    # 3축: 일

# === 콘텐츠 ===
type: event                                 # event | meeting | note | action
title: "에이아이당 주간 회의"
summary: ""                                 # AI 요약 (나중에 채워짐)

# === 메타데이터 (디테일) ===
source: gcal                                # kakao | gmail | gcal | slack | plaud
source_id: "gcal_abc123"
created: 2026-03-18T14:00:00
status: raw                                 # raw | enriched | reviewed
tags: []
---
```

**핵심: `date`, `participants`, `project`가 Dataview 쿼리의 3축 필터**

---

## 6. 사람 노트 — 2축 허브

People 노트는 **해당 인물과의 모든 상호작용을 자동 집계하는 라이브 대시보드**다.

```markdown
---
type: person
name: 유민승
aliases: [민승, 민승님, Minseung, minseung@example.com]
organization: "[[테크노크라츠]]"
role: 대표
kakao_name: 유민승
projects:
  - "[[테크노크라츠]]"
  - "[[에이아이당]]"
relationship: collaborator
last_contact: 2026-03-18
---
# 유민승

## 최근 활동
```dataview
TABLE WITHOUT ID
  file.link AS "내용",
  date AS "날짜",
  source AS "출처",
  project AS "프로젝트"
FROM "1. INPUT"
WHERE contains(participants, this.file.link)
SORT date DESC
LIMIT 15
```

## 미완료 액션
```dataview
TASK
FROM "1. INPUT"
WHERE contains(text, "유민승") AND !completed
```

## 메모
_수동 관찰/메모_
```

**사람 매칭 전략 (정확 일치만, 퍼지 매칭 금지):**
- `kakao_name`: 카카오톡 표시 이름 정확 일치
- `aliases`: 이메일, Slack ID, 다른 이름 정확 일치
- 모호한 매칭 → `[[Unknown: 카톡닉네임]]`으로 플래그 → 수동 해결

---

## 7. 프로젝트 노트 — 3축 허브

```markdown
---
type: project
name: 에이아이당
aliases: [에이아이당, AIPARTY, AI당]
keywords: [에이아이당, aiparty, AI당, 정당, 창당]
status: active
people:
  - "[[🙍‍♂️유민승]]"
---
# 에이아이당 AIPARTY

## 최근 활동
```dataview
TABLE WITHOUT ID
  file.link AS "내용",
  date AS "날짜",
  participants AS "사람"
FROM "1. INPUT"
WHERE project = this.file.link
SORT date DESC
LIMIT 15
```

## 미팅
```dataview
LIST
FROM "1. INPUT/Meeting"
WHERE project = this.file.link
SORT date DESC
```

## 미완료 액션
```dataview
TASK
FROM "1. INPUT"
WHERE contains(text, "에이아이당") AND !completed
```

## 의사결정 로그
_AI 추출 또는 수동 기록_
```

---

## 8. 데일리 노트 — 3축 대시보드

데일리 노트는 **데이터를 저장하지 않는다.** Dataview 쿼리로 당일 이벤트를 집계할 뿐이다.

```markdown
---
date: {{date}}
type: daily
---
#### [[{{yesterday}} |◀︎]] {{date}} [[{{tomorrow}} |▶︎]]

## Morning Brief
> _08:00 자동 생성 | 미생성 시 "⏳ 생성 중..." 표시_

---
## ==잡서


---
## 오늘의 기록 (시간축)
```dataview
TABLE WITHOUT ID
  file.link AS "내용",
  participants AS "사람",
  project AS "프로젝트",
  source AS "출처"
FROM "1. INPUT/{{year-month}}"
WHERE date = date("{{date}}")
SORT created ASC
```

## 사람 (사람축)
```dataview
TABLE WITHOUT ID
  participants AS "사람",
  count(rows) AS "상호작용 수"
FROM "1. INPUT/{{year-month}}"
WHERE date = date("{{date}}")
FLATTEN participants
GROUP BY participants
SORT count(rows) DESC
```

## 프로젝트 (일축)
```dataview
TABLE WITHOUT ID
  project AS "프로젝트",
  count(rows) AS "이벤트 수"
FROM "1. INPUT/{{year-month}}"
WHERE date = date("{{date}}") AND project
GROUP BY project
SORT count(rows) DESC
```

---
## 리뷰
> _23:00 AI 일일 요약 자동 삽입_

---
## 액션 아이템
```dataview
TASK
FROM "1. INPUT/{{year-month}}"
WHERE date = date("{{date}}") AND !completed
```
```

---

## 9. 원본 데이터 보존 전략

### .md = 소스 오브 트루스, SQLite = 재구축 가능 인덱스

```
                   쓰기 순서
Source API ──▶ .md 파일 (1. INPUT/) ──▶ SQLite 인덱스
                 ↑ 소스 오브 트루스      ↑ 파생 데이터
                 ↑ 영구 보존             ↑ 삭제 후 rebuild 가능
```

**SQLite에만 존재하는 것 (운영 데이터, 영구 보존 불필요):**
- `sync_cursors` — 어디까지 수집했는지 (커서)
- `processing_queue` — 처리 대기열 상태
- `health_checks` — 시스템 건강 상태

**SQLite rebuild 명령:**
```bash
onlime rebuild-index
# 1. INPUT/**/*.md 전체 스캔
# frontmatter 파싱 → events 테이블 재생성
# people/ 폴더 스캔 → people 테이블 재생성
# projects/ 폴더 스캔 → projects 테이블 재생성
```

### 데이터 볼륨 관리

| 주기 | 예상 파일 수 | 관리 전략 |
|------|-------------|-----------|
| 월간 | ~800-1,200 | 월별 서브폴더 (`2026-03/`) |
| 연간 | ~10,000-15,000 | 연말에 `Archive/YYYY/`로 이동 |
| 3년 | ~30,000-45,000 | Archive는 Dataview 제외 설정 |

**Dataview 성능 보장:**
- 모든 쿼리에 `FROM "1. INPUT/2026-03"` 스코프 강제
- `FROM ""` (전체 볼트 스캔) 절대 사용 금지
- Archive 폴더는 `.obsidian/app.json`에서 Dataview 제외

---

## 10. Collector 설계 — MCP 문제 해결

### 핵심 결정: googleapis 직접 사용 (MCP 아님)

**R5가 발견한 치명적 문제:** MCP 도구(`mcp__claude_ai_Gmail__*`)는 Claude Code 세션 내에서만 동작. Node.js 데몬에서 호출 불가.

**해결:** `googleapis` npm 패키지로 Gmail/Calendar API 직접 호출. 인증은 OAuth2 + refresh token.

```
MCP 서버 → 대화형 Claude Code에서만 사용 (ad-hoc 질문용)
googleapis  → 데몬에서 사용 (자동 수집용)
```

### 소스별 Collector

| 소스 | 도구 | 주기 | Phase |
|------|------|------|-------|
| 카카오톡 | kmsg CLI | 5min | **Phase 1** |
| Gmail | googleapis | 5min | **Phase 1** |
| Google Calendar | googleapis | 15min | **Phase 1** |
| Plaud | chokidar (폴더 감시) | 즉시 | **Phase 2** |
| Slack | @slack/web-api | 5min | Phase 3 |

### 수집 → 쓰기 → 인덱싱 흐름 (KakaoTalk 예시)

```
1. kmsg read "테크노크라츠 유민승" --limit 30 --json
2. 새 메시지 감지 (sync_cursor 비교)
3. .md 파일 생성:
   - frontmatter: date, participants, project, source
   - body: 대화 내용
   - 사람 매칭: "유민승" → people 테이블 조회 → [[🙍‍♂️유민승]]
   - 프로젝트 매칭: "테크노크라츠" → projects 테이블 조회 → [[테크노크라츠]]
4. atomic write (tmp→rename) → 1. INPUT/2026-03/
5. SQLite 인덱싱: frontmatter → events 테이블 INSERT
6. sync_cursor 업데이트 (트랜잭션으로 4-5-6 원자적)
7. macOS 알림: "카톡 5건 수집 (테크노크라츠 유민승)"
```

---

## 11. OpenClaw — 메시징 브릿지 + 업무 실행

### 역할 명확화

```
데이터 수집:  Node.js 데몬 (googleapis + kmsg + chokidar)  ← OpenClaw 아님
AI 처리:     Anthropic API 직접 호출                       ← OpenClaw 아님
메시지 발송:  OpenClaw + kmsg send (승인 후)               ← OpenClaw의 역할
업무 실행:   OpenClaw Lobster 워크플로우 (승인 게이트)      ← OpenClaw의 역할
```

### Lobster 워크플로우 예시 — 미팅 요청 처리

```yaml
name: meeting-request-handler
steps:
  - id: detect_request
    description: "카톡에서 미팅 요청 감지"
  - id: check_calendar
    run: node scripts/check-availability.js --from tomorrow --to "+7d"
  - id: suggest_times
    run: claude -p "3개 가능 시간 제안" --output-format json
    stdin: $check_calendar.json
  - id: approve
    approval: "{{sender}}에게 이 시간들을 제안할까요?"
  - id: send_reply
    run: kmsg send "{{sender}}" "{{reply}}"
    when: $approve.approved
```

### 4단계 승인 레벨

| 레벨 | 행동 | 승인 | 예시 |
|------|------|------|------|
| L0 | 읽기/수집/요약 | 자동 | 카톡 수집, 이메일 읽기, 일일 요약 |
| L1 | 알림 발송 | 자동 (로깅) | "미팅 30분 전" 알림 |
| L2 | 메시지 발송 | **사용자 승인 필수** | 카톡 답장, 이메일 회신 |
| L3 | 중요 커뮤니케이션 | **이중 확인** | 공식 메일, 다수 수신자 |

### Shadow Mode (첫 2주)

실제 실행 전 "이렇게 했을 것" 로그를 축적:
```
[Shadow] 유민승에게 답장 제안: "내일 14시 강남역 카페에서 뵙겠습니다"
[Shadow] 김소희에게 이메일 초안: "쇼츠 제작 일정 확인 요청"
```
2주간 로그 검토 후 정확도가 80%+ 이면 L1부터 점진적 활성화.

---

## 11.5. 텔레그램 원격 제어 — 입력/소통 인터페이스

### 왜 텔레그램인가

| 채널 | 장점 | 단점 |
|------|------|------|
| **텔레그램** | Bot API 완전 무료, 무제한 메시지, 리치 포맷(버튼/인라인키보드), 모든 디바이스, 빠른 봇 생성(5분) | 한국에서 일상 메신저 아님 |
| 카카오톡 | 한국 일상 메신저 | Bot API 없음, kmsg는 macOS Accessibility만, 모바일에서 명령 불가 |
| 슬랙 | 업무 도구 | 개인 워크스페이스 필요, rate limit 엄격 |
| Claude Dispatch | Anthropic 공식, 모바일→데스크톱 원격 | Max 구독 전용, "느리고 불안정, 성공률 ~50%" (MacStories 테스트), 맥 깨어있어야 함 |

**결론: 텔레그램이 "명령 채널"로 최적.** 카카오톡은 "수집 채널"로 유지. 역할 분리:
- **카카오톡** = 실제 사람들과 소통하는 곳 (수집 대상)
- **텔레그램** = AI 시스템과 소통하는 곳 (명령/보고 채널)

### 3가지 접근법 비교

| | OpenClaw + 텔레그램 | Claude Code + 텔레그램 (DIY) | Claude Dispatch (Cowork) |
|---|---|---|---|
| **설정 난이도** | 5분 (BotFather → config.json5) | 30분 (ccgram 또는 claude-code-telegram 설치) | 즉시 (Max 구독자) |
| **항상 실행** | ✅ Gateway 데몬 24/7 | ✅ Node.js 봇 서버 24/7 | ❌ Mac 깨어있어야 + Claude Desktop 열려있어야 |
| **메시지 발송** | ✅ 카톡/슬랙/이메일 발송 가능 | ⚠️ `claude -p` + kmsg/googleapis로 가능하지만 느림 | ⚠️ Cowork 도구 통해 가능하지만 불안정 |
| **승인 워크플로우** | ✅ Lobster approval gate + 텔레그램 인라인 버튼 | ⚠️ 직접 구현 필요 | ❌ 없음 |
| **비용** | $0 (텔레그램 Bot API 무료) + OpenClaw 무료 | $0 (텔레그램) + Anthropic API 비용 | Max 구독 ($100/월) |
| **안정성** | 높음 (텔레그램 Bot API 매우 안정) | 중간 (claude -p 세션 시작 오버헤드) | 낮음 (~50% 성공률) |
| **AI 품질** | 모든 LLM 사용 가능 (Claude, GPT, etc.) | Claude 전용 (최고 품질) | Claude 전용 |
| **파일 접근** | ⚠️ OpenClaw 스킬 통해 간접 | ✅ 볼트 직접 읽기/쓰기 | ✅ Cowork 도구로 접근 |

### 권장 아키텍처: 하이브리드 (OpenClaw + Claude Code)

```
┌─────────────────────────────────────────────────────────┐
│                    텔레그램 (모바일)                       │
│                                                          │
│  📱 사용자                                               │
│   │                                                      │
│   ├─ "오늘 할일 알려줘"          → 브리핑 요청            │
│   ├─ "유민승에게 카톡 보내: ..."  → 메시지 발송 명령       │
│   ├─ "에이아이당 진행상황?"       → 정보 조회              │
│   ├─ "내일 14시 미팅 잡아줘"     → 캘린더 생성 명령       │
│   └─ [승인] / [거부] 버튼         → 워크플로우 승인        │
└──────────────────────┬──────────────────────────────────┘
                       │ Telegram Bot API
                       │
┌──────────────────────▼──────────────────────────────────┐
│              OpenClaw Gateway (로컬 Mac)                  │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  텔레그램 어댑터                                   │    │
│  │  - @BotFather에서 생성한 봇 토큰                  │    │
│  │  - 사용자 ID 화이트리스트 (owner만 접근)           │    │
│  │  - 인바운드: 텍스트 명령 파싱                      │    │
│  │  - 아웃바운드: 리치 메시지 (마크다운 + 인라인 버튼) │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                                │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │  명령 라우터                                      │    │
│  │                                                    │    │
│  │  /briefing  → context.json 읽기 → AI 요약 생성    │    │
│  │  /send      → Lobster 워크플로우 (승인 게이트)    │    │
│  │  /status    → SQLite 쿼리 → 프로젝트 상태        │    │
│  │  /schedule  → googleapis 캘린더 생성              │    │
│  │  /search    → claude -p "볼트 검색" (고급 쿼리)   │    │
│  │  자유 텍스트  → claude -p (자연어 명령 해석)       │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  스케줄 푸시 (Heartbeat + Cron)                    │    │
│  │                                                    │    │
│  │  08:00  → 텔레그램으로 Morning Brief 푸시          │    │
│  │  미팅-60분 → Pre-Meeting Brief 푸시               │    │
│  │  23:00  → Daily Summary 푸시                      │    │
│  │  실패 시 → "⚠️ 카톡 수집 2시간째 실패" 경고 푸시  │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 텔레그램 봇 설정 (5분)

```bash
# 1. @BotFather에서 봇 생성
# /newbot → "Onlime Assistant" → @onlime_dongin_bot
# → 토큰 받기: 123456:ABC-DEF...

# 2. OpenClaw config에 텔레그램 추가
# ~/.openclaw/config.json5
{
  channels: {
    telegram: {
      adapter: "telegram",
      token: "123456:ABC-DEF...",
      allowedUsers: [YOUR_TELEGRAM_USER_ID],  // owner만
      defaultMode: "agent"
    }
  }
}

# 3. 또는 Claude Code Telegram (ccgram 방식)
# npm install -g ccgram
# ccgram init --token "123456:ABC-DEF..." --claude-path $(which claude)
```

### 텔레그램 메시지 포맷 예시

**Morning Brief (08:00 자동 푸시):**
```
🌅 Morning Brief — 2026-03-19

📅 오늘 일정:
• 10:00 더해커톤 주간회의
• 14:00 유민승 미팅 (에이아이당)
• 17:00 참치상사 통화

📋 미완료 액션:
• ⚠️ 김지훈 디자인 리뷰 (3일째)
• 유민승 계약서 초안

🎯 오늘의 우선순위:
1. 김지훈 팔로업 (가장 오래된 블로커)
2. 유민승 미팅 준비
3. 더해커톤 회의 안건 정리

[상세 보기 🔗] [Obsidian 열기 🔗]
```

**승인 요청 (L2 메시지 발송):**
```
📤 메시지 발송 요청

수신자: 유민승 (카카오톡)
내용: "내일 14시 강남역 카페에서 뵙겠습니다.
에이아이당 MVP 범위 관련 자료 준비해오겠습니다."

[✅ 발송] [✏️ 수정] [❌ 취소]
```

**정보 조회 응답:**
```
📊 에이아이당 진행상황

이번 주 활동: 12건
• 카톡 8건 (유민승, 김소희)
• 이메일 3건
• 미팅 1건

최근 결정:
• MVP 범위를 채팅+이메일로 축소 (3/18)

미해결 액션:
• [ ] 유민승 계약서 초안
• [ ] 김소희 쇼츠 기획안 검토

[전체 보기 📋]
```

### 자연어 명령 처리 흐름

```
사용자: "유민승한테 내일 미팅 확인 카톡 보내줘"
   │
   ▼
OpenClaw: 자연어 파싱 → 의도 추출
   │  수신자: 유민승
   │  채널: 카카오톡 (kmsg)
   │  내용: 미팅 확인 메시지
   │
   ▼
AI 메시지 초안 생성:
   "유민승님, 내일 14시 미팅 확인 부탁드립니다.
    장소는 강남역 카페로 정해진 것 맞나요?"
   │
   ▼
텔레그램으로 승인 요청:
   [✅ 발송] [✏️ 수정] [❌ 취소]
   │
   ▼ (사용자가 ✅ 터치)
   │
kmsg send "테크노크라츠 유민승" "유민승님, 내일 14시..."
   │
   ▼
텔레그램 확인: "✅ 발송 완료 (14:32)"
Onlime 데몬: 다음 수집 시 이 발송 메시지도 .md로 기록
```

### Claude Dispatch — 보조 채널로 활용 (선택)

Claude Dispatch(Cowork Remote)는 **주 채널로는 부적합**하지만, Max 구독자라면 보조적으로 활용 가능:

```
주 채널: 텔레그램 (OpenClaw)
  - 아침/저녁 브리핑
  - 메시지 발송 명령
  - 승인 워크플로우
  - 간단한 상태 조회

보조 채널: Claude Dispatch (선택)
  - 복잡한 자연어 질문 ("지난달 유민승과 에이아이당 관련 모든 대화를 요약해줘")
  - 볼트 깊이 검색 (Obsidian 파일 직접 읽기)
  - 코드 수정/디버깅 (Onlime 시스템 자체 개선)
```

### 구현 로드맵에 반영

| Phase | 텔레그램 관련 태스크 |
|-------|-------------------|
| **Phase 2** | 텔레그램 봇 생성 + OpenClaw 텔레그램 어댑터 설정 |
| **Phase 2** | 스케줄 푸시: Morning Brief, Daily Summary → 텔레그램 |
| **Phase 2** | 시스템 장애 알림 → 텔레그램 |
| **Phase 3** | 자연어 명령 처리 (메시지 발송, 일정 생성) |
| **Phase 3** | 승인 워크플로우 (인라인 버튼) |
| **Phase 3** | Shadow Mode 결과를 텔레그램으로 리포팅 |

---

## 12. AI 처리 — 현실적 비용 계산

### 3-Tier 전략 (v2와 동일, 비용만 현실화)

| Tier | 용도 | 모델 | 월간 비용 |
|------|------|------|----------|
| 1 | 규칙 기반 (사람/프로젝트 매칭, regex) | 없음 | $0 |
| 2 | 분류/중요도 | Haiku | ~$0.50 |
| 3 | 요약/브리프/리뷰 | Sonnet via `claude -p` | ~$12-18 |
| **합계** | | | **$13-19/월** |

### `claude -p` 컨텍스트 문제 해결

**문제:** 각 `claude -p` 호출은 무상태. "어제 뭐 했는지" 모름.

**해결:** 데몬이 매일 23:00에 `~/.onlime/context/daily-context.json` 생성:
```json
{
  "date": "2026-03-18",
  "pending_actions": ["유민승 계약서 초안", "더해커톤 디자인 피드백"],
  "key_decisions": ["에이아이당 MVP 범위 축소"],
  "upcoming_meetings": ["3/19 14:00 유민승 미팅"],
  "people_contacted": ["유민승(4회)", "김소희(2회)"],
  "projects_active": ["에이아이당(60%)", "더해커톤(25%)"]
}
```

`claude -p` Morning Brief가 이 파일 하나만 읽으면 전체 맥락 파악 가능. 토큰 효율적.

### Skill-as-Markdown 패턴 (mgonto 참조)

`claude -p` 프롬프트를 코드 인라인이 아닌 `skills/*.md`에 저장:

```markdown
# skills/morning-brief.md
당신은 최동인의 AI 비서입니다.
~/.onlime/context/daily-context.json을 읽고,
오늘의 모닝 브리프를 작성하세요.

포함할 내용:
1. 오늘 일정 (캘린더)
2. 미완료 액션 아이템 (어제로부터)
3. 팔로업 필요 (응답하지 않은 이메일, 오래된 액션)
4. 프로젝트별 오늘의 우선순위

형식: 한국어, [[위키링크]] 사용, 간결하게.
```

버전 관리 가능, 반복 개선 가능, Git 추적 가능.

---

## 13. 셀프 개선 루프 (PAI 참조)

### 피드백 시스템

```sql
CREATE TABLE ratings (
  id INTEGER PRIMARY KEY,
  target_type TEXT,        -- 'morning_brief' | 'daily_summary' | 'pre_meeting'
  target_date TEXT,
  rating INTEGER,          -- 1-5
  comment TEXT,
  created_at TEXT
);
```

사용자가 AI 생성물에 1-5점 평점 부여 (Obsidian 내 간단한 인라인 필드):
```markdown
## Morning Brief
> ... AI 생성 내용 ...
> rating:: 4
> feedback:: 프로젝트별 우선순위가 도움됐음. 팔로업 제안이 더 구체적이면 좋겠음.
```

### 주간 자동 분석

일요일 리뷰 시 rating 데이터 분석:
- 평점 1-2인 출력의 공통 패턴 → `config/ai-rules.json`에 개선 규칙 추가
- 예: "프리미팅 브리프에서 최근 카톡 내용이 누락됨" → 규칙 추가: "프리미팅 시 해당 인물의 최근 3일 카톡 반드시 포함"

---

## 14. 리뷰 시스템 (일간/주간/월간)

### 일일 리뷰 (23:00, Anthropic API)

```markdown
## 일일 리뷰 — 2026-03-18

### 한 줄 요약
> 에이아이당 미팅 확정, 더해커톤 디자인 블로커 지속 3일째

### 수치
- 상호작용: 24건 (카톡 15, 이메일 6, 미팅 3)
- 액션: 3개 생성, 2개 완료, 5개 미해결

### 주요 사람
| 사람 | 건수 | 핵심 |
|------|------|------|
| [[🙍‍♂️유민승]] | 8 | 에이아이당 미팅 확정 |

### 프로젝트 진행
- **[[에이아이당]]**: 미팅 확정 ✅
- **[[더해커톤]]**: 디자인 피드백 대기 (3일째) ⚠️

### 팔로업 필요
- [ ] [[🙍‍♂️김지훈]] 디자인 리뷰 회신 (3일 미응답)
- [ ] 유민승 계약서 초안 전달

### AI 관찰
> 더해커톤이 3일째 정체. 김지훈에게 직접 연락 권장.
```

### 주간 리뷰 (일요일 22:00)

`2. OUTPUT/Weekly/2026-W12.md` — 프로젝트별 진행, 사람별 인터랙션 요약, stale 항목 경고, 다음 주 우선순위 AI 제안.

### 월간 리뷰 (1일 22:00)

`2. OUTPUT/Monthly/2026-03.md` — 프로젝트 궤적, 네트워크 변화, 시간 배분 분석, 전략적 정렬 체크.

---

## 15. 구현 로드맵 (현실적)

### Phase 1: Working MVP (2주)

**목표:** 카톡+Gmail+Calendar → 개별 .md 노트 → Dataview 대시보드

- [ ] SQLite 스키마 (`db.ts`) — sync_cursors, events 인덱스
- [ ] `kakao-collector.ts` — 기존 kakao-monitor 리팩터, 개별 .md 노트 생성
- [ ] `gmail-collector.ts` — googleapis OAuth + 메일 수집 → .md
- [ ] `gcal-collector.ts` — googleapis OAuth + 이벤트 수집 → .md
- [ ] `enricher.ts` — 규칙 기반 사람/프로젝트 매칭, [[위키링크]] 삽입
- [ ] `writer.ts` — 통합 .md 파일 생성기 (atomic write)
- [ ] People 노트 frontmatter에서 `contacts` 자동 추출 (수동 입력 X)
- [ ] 데일리 노트 Templater 템플릿 (Dataview 대시보드)
- [ ] `@anthropic-ai/sdk` — OpenClaw 대체 요약기
- [ ] macOS 알림 heartbeat
- [ ] `com.onlime.daemon.plist` LaunchAgent
- [ ] `onlime rebuild-index` 명령

### Phase 2: 심화 통합 + 텔레그램 (2주)

- [ ] **텔레그램 봇 생성** (@BotFather) + OpenClaw 텔레그램 어댑터 설정
- [ ] **Morning Brief → 텔레그램 푸시** (08:00, context.json 기반)
- [ ] **Daily Summary → 텔레그램 푸시** (23:00, Anthropic API)
- [ ] **시스템 장애 알림 → 텔레그램** (수집 실패, 데몬 크래시 등)
- [ ] Plaud 폴더 감시 (chokidar) + Calendar 시간 매칭
- [ ] Pre-Meeting Brief (30분 전 체크) → 텔레그램 + Obsidian
- [ ] 피드백 rating 시스템 (SQLite + Obsidian inline field)

### Phase 3: 업무 실행 + 텔레그램 명령 (2주)

- [ ] **텔레그램 자연어 명령** ("유민승에게 카톡 보내줘", "내일 14시 미팅 잡아줘")
- [ ] **텔레그램 승인 워크플로우** (인라인 버튼 [✅ 발송] [❌ 취소])
- [ ] OpenClaw Lobster 워크플로우 설정
- [ ] Shadow Mode 2주간 로그 축적 → 결과를 텔레그램으로 리포팅
- [ ] L0→L1 점진적 실행 권한 확대
- [ ] Slack collector (`@slack/web-api`)
- [ ] Weekly Review 자동 생성 → 텔레그램 푸시

### Phase 4: 고도화 (지속)

- [ ] Monthly Review
- [ ] 셀프 개선 루프 (주간 rating 분석)
- [ ] Vault health 모니터링 (orphan, staleness)
- [ ] Screenpipe 연동 (선택)
- [ ] 로컬 모델 Tier 2 (MLX on Apple Silicon)

---

## 16. 핵심 의존성

```json
{
  "dependencies": {
    "better-sqlite3": "^11.0.0",
    "googleapis": "^144.0.0",
    "google-auth-library": "^9.0.0",
    "@anthropic-ai/sdk": "^1.0.0",
    "node-cron": "^3.0.3",
    "chokidar": "^4.0.0",
    "gray-matter": "^4.0.3",
    "uuid": "^10.0.0"
  }
}
```

**제거:** OpenClaw CLI/API 의존성 (AI 처리용)
**유지:** OpenClaw (메시징 브릿지 전용, Phase 3)
**추가하지 않음:** Redis, Neo4j, Docker, n8n — 개인 도구에 과잉

---

## 17. 설계 원칙 요약

| 원칙 | 설명 |
|------|------|
| **3축 (시간/사람/일)** | 모든 네비게이션과 쿼리의 기본 축. 소스는 메타데이터 |
| **.md = 진실** | Obsidian 볼트의 .md 파일이 유일한 소스 오브 트루스 |
| **SQLite = 인덱스** | 삭제 후 rebuild 가능. 운영 상태만 SQLite 전용 |
| **Heartbeat 필수** | 시스템이 일하고 있는지 사용자가 항상 알 수 있어야 함 |
| **googleapis > MCP** | 데몬에서 직접 API 호출. MCP는 대화형 전용 |
| **규칙 우선, AI 보강** | 사람/프로젝트 매칭은 규칙. AI는 요약/분석에만 |
| **정확 일치만** | 한국어 이름 퍼지 매칭 금지. 정확 매칭 + Unknown 플래그 |
| **Push, don't wait** | 텔레그램 + macOS 알림으로 브리프/경고 푸시. "찾아봐야 아는" 시스템 X |
| **채널 분리** | 카카오톡 = 사람들과 소통 (수집), 텔레그램 = AI와 소통 (명령/보고) |
| **셀프 개선** | 피드백 루프로 AI 출력 품질 지속 향상 |
| **현실적 비용** | $15-20/월. $5 환상 X |

---

## 부록 A: Onlime의 유니크 밸류 (9개 시스템 비교 결과)

> "Onlime은 **한국어 멀티 프로젝트 운영자**의 **7+ 이질적 소스**에서 **수동 입력 없이** 데이터를 수집하고, **시간/사람/일 3축**으로 정규화하여, **로컬 Obsidian 볼트**에 **링크된 지식 그래프**로 축적하는 유일한 시스템이다."

기존 어떤 시스템도 이 조합을 제공하지 않음:
- agent-second-brain: 단일 입력 (Telegram 음성)
- PAI: 수동 대화형, 자동 수집 없음
- Monica: 수동 CRM 입력
- COG: 수동 노트 정리
- mgonto: 수집 없음, 실행만

---

## 부록 B: 리서치 참여 에이전트

| 역할 | 인원 | 주요 발견 |
|------|------|----------|
| 리서처 | 10 | 18개 GitHub 레포, 15명 실무자, 3개 국가 생태계 분석 |
| 리뷰어 | 5 | 1 CRITICAL + 7 MAJOR 이슈, UX 3.7/10, 18개 리스크 레지스터 |
| 사용자 | 1 | 3축 원칙 (시간/사람/일), OpenClaw 업무 실행 요구 |
