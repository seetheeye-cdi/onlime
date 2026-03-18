import Anthropic from "@anthropic-ai/sdk";
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import matter from "gray-matter";
import { getDb } from "../db.js";

const VAULT_PATH = "/Users/aiparty/Desktop/Obsidian_sinc";
const CONTEXT_DIR = join(homedir(), ".onlime", "context");

function todayStr(dateIso?: string): string {
  const d = dateIso ? new Date(dateIso) : new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function monthFolder(dateIso?: string): string {
  const d = dateIso ? new Date(dateIso) : new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

interface DayData {
  events: Array<{
    type: string;
    source: string;
    title: string;
    participants: string[];
    project: string;
    body: string;
  }>;
  stats: {
    total: number;
    bySource: Record<string, number>;
    byProject: Record<string, number>;
    people: string[];
  };
}

async function collectDayData(date: string): Promise<DayData> {
  const datePrefix = date.replace(/-/g, "");
  const inputDir = join(VAULT_PATH, "1. INPUT", monthFolder(date));

  const events: DayData["events"] = [];
  const stats: DayData["stats"] = {
    total: 0,
    bySource: {},
    byProject: {},
    people: [],
  };

  try {
    const files = await readdir(inputDir);
    const dayFiles = files.filter((f) => f.startsWith(datePrefix) && f.endsWith(".md"));

    for (const file of dayFiles) {
      const raw = await readFile(join(inputDir, file), "utf-8");
      const { data, content } = matter(raw);

      const event = {
        type: (data.type as string) || "unknown",
        source: (data.source as string) || "unknown",
        title: (data.title as string) || file,
        participants: (data.participants as string[]) || [],
        project: (data.project as string) || "",
        body: content.slice(0, 500), // 토큰 절약을 위해 본문 500자로 제한
      };

      events.push(event);
      stats.total++;
      stats.bySource[event.source] = (stats.bySource[event.source] || 0) + 1;
      if (event.project) {
        stats.byProject[event.project] = (stats.byProject[event.project] || 0) + 1;
      }
      for (const p of event.participants) {
        if (!stats.people.includes(p)) stats.people.push(p);
      }
    }
  } catch {
    // 폴더가 없으면 빈 데이터
  }

  return { events, stats };
}

export async function generateDailySummary(date?: string): Promise<string> {
  const targetDate = date || todayStr();
  const dayData = await collectDayData(targetDate);

  if (dayData.stats.total === 0) {
    return `> 오늘 수집된 이벤트가 없습니다.`;
  }

  // Anthropic API 호출 시도
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return buildFallbackSummary(targetDate, dayData);
  }

  try {
    const client = new Anthropic({ apiKey });

    const eventsContext = dayData.events
      .map(
        (e) =>
          `[${e.source}] ${e.title} | 참여: ${e.participants.join(", ")} | 프로젝트: ${e.project || "없음"}\n${e.body}`
      )
      .join("\n---\n");

    const message = await client.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 1024,
      messages: [
        {
          role: "user",
          content: `당신은 최동인의 AI 비서입니다. 오늘(${targetDate})의 활동을 요약해주세요.

오늘의 이벤트 (${dayData.stats.total}건):
${eventsContext}

다음 형식으로 작성하세요 (한국어):

### 한 줄 요약
> (오늘의 핵심을 한 문장으로)

### 수치
- 상호작용: N건 (소스별 분포)
- 주요 사람: (가장 많이 상호작용한 사람)

### 프로젝트 진행
- (프로젝트별 1줄 요약, ✅/⚠️/❌ 상태 표시)

### 팔로업 필요
- [ ] (미완료 항목이 있으면)

### AI 관찰
> (패턴이나 주의할 점)

사람 이름은 [[위키링크]] 형식을 유지하세요.`,
        },
      ],
    });

    const text =
      message.content[0].type === "text" ? message.content[0].text : "";
    return text || buildFallbackSummary(targetDate, dayData);
  } catch (err) {
    console.error("[summarizer] Anthropic API failed:", err);
    return buildFallbackSummary(targetDate, dayData);
  }
}

function buildFallbackSummary(date: string, data: DayData): string {
  const sourceLines = Object.entries(data.stats.bySource)
    .map(([s, n]) => `${s} ${n}건`)
    .join(", ");

  const projectLines = Object.entries(data.stats.byProject)
    .map(([p, n]) => `- ${p}: ${n}건`)
    .join("\n");

  const peopleList = data.stats.people.slice(0, 10).join(", ");

  return `### 수치
- 총 이벤트: ${data.stats.total}건 (${sourceLines})
- 주요 사람: ${peopleList || "없음"}

### 프로젝트
${projectLines || "- (프로젝트 태깅 없음)"}

> _AI 요약 생성 실패. ANTHROPIC_API_KEY를 설정하세요._`;
}

/**
 * claude -p 모닝 브리프용 컨텍스트 파일 생성
 */
export async function generateContext(date?: string): Promise<void> {
  const targetDate = date || todayStr();
  const dayData = await collectDayData(targetDate);

  // SQLite에서 미완료 액션 조회
  const db = getDb();
  const pendingActions = db
    .prepare(
      `SELECT title, participants, project FROM events
       WHERE type = 'action' AND status != 'reviewed'
       ORDER BY timestamp DESC LIMIT 20`
    )
    .all() as Array<{ title: string; participants: string; project: string }>;

  // 내일 일정 (간단히 SQLite에서 조회)
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const tomorrowStr = todayStr(tomorrow.toISOString());

  const context = {
    date: targetDate,
    pending_actions: pendingActions.map((a) => a.title || "제목 없음"),
    key_decisions: [], // Phase 2에서 구현
    upcoming_meetings: [], // Phase 2에서 GCal 연동 후 구현
    people_contacted: dayData.stats.people.slice(0, 20),
    projects_active: Object.entries(dayData.stats.byProject).map(
      ([name, count]) => `${name}(${count}건)`
    ),
    stats: dayData.stats,
  };

  await mkdir(CONTEXT_DIR, { recursive: true });
  await writeFile(
    join(CONTEXT_DIR, "daily-context.json"),
    JSON.stringify(context, null, 2),
    "utf-8"
  );

  console.log(`[summarizer] Context written to ${CONTEXT_DIR}/daily-context.json`);
}

// 직접 실행 가능
if (
  process.argv[1]?.endsWith("summarizer.ts") ||
  process.argv[1]?.endsWith("summarizer.js")
) {
  const date = process.argv[2];
  const summary = await generateDailySummary(date);
  console.log(summary);
}
