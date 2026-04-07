// Pre-Meeting Brief 생성기
// 매 30분마다 실행. 60분 이내 시작하는 미팅을 찾아 브리프 생성.
// crontab: every 30min — npx tsx src/scripts/pre-meeting.ts

import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import matter from "gray-matter";
import Anthropic from "@anthropic-ai/sdk";
import { getDb } from "../db.js";
import { writeEventNote } from "../writer.js";
import { notify } from "../notify.js";
import { sendMessage } from "../collectors/telegram-bot.js";
import type { OnlimeEvent } from "../types.js";
import { v4 as uuid } from "uuid";

const VAULT_PATH = "/Users/aiparty/Desktop/Obsidian_sinc";

interface UpcomingMeeting {
  title: string;
  start: string;
  participants: string[];
  project: string;
  source_id: string;
}

function isWithinWindow(startIso: string, windowMinutes: number): boolean {
  const start = new Date(startIso).getTime();
  const now = Date.now();
  const diff = start - now;
  return diff > 0 && diff <= windowMinutes * 60 * 1000;
}

async function findUpcomingMeetings(): Promise<UpcomingMeeting[]> {
  const db = getDb();

  // 60분 이내 시작하는 캘린더 이벤트
  const now = new Date().toISOString();
  const oneHour = new Date(Date.now() + 60 * 60 * 1000).toISOString();

  const events = db
    .prepare(
      `SELECT source_id, title, timestamp, participants, project
       FROM events
       WHERE source = 'gcal' AND timestamp BETWEEN ? AND ?`
    )
    .all(now, oneHour) as Array<{
    source_id: string;
    title: string;
    timestamp: string;
    participants: string;
    project: string;
  }>;

  return events
    .filter((e) => isWithinWindow(e.timestamp, 60))
    .map((e) => ({
      title: e.title || "미팅",
      start: e.timestamp,
      participants: JSON.parse(e.participants || "[]"),
      project: e.project || "",
      source_id: e.source_id,
    }));
}

async function getPersonContext(wikilink: string): Promise<string> {
  // People 노트에서 최근 활동 가져오기
  const db = getDb();

  const recentEvents = db
    .prepare(
      `SELECT title, source, timestamp FROM events
       WHERE participants LIKE ? ORDER BY timestamp DESC LIMIT 5`
    )
    .all(`%${wikilink}%`) as Array<{
    title: string;
    source: string;
    timestamp: string;
  }>;

  if (recentEvents.length === 0) return "최근 접촉 기록 없음";

  return recentEvents
    .map((e) => `- [${e.source}] ${e.title} (${e.timestamp.split("T")[0]})`)
    .join("\n");
}

async function generateBrief(meeting: UpcomingMeeting): Promise<string> {
  // 참석자별 컨텍스트 수집
  const participantContexts: string[] = [];
  for (const p of meeting.participants) {
    const ctx = await getPersonContext(p);
    participantContexts.push(`### ${p}\n${ctx}`);
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    // API 없이 기본 브리프
    return buildFallbackBrief(meeting, participantContexts);
  }

  try {
    const client = new Anthropic({ apiKey });

    const msg = await client.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 800,
      messages: [
        {
          role: "user",
          content: `최동인의 미팅 브리프를 생성해주세요.

미팅: ${meeting.title}
시간: ${new Date(meeting.start).toLocaleString("ko-KR")}
참석자: ${meeting.participants.join(", ")}
프로젝트: ${meeting.project || "미지정"}

참석자 최근 활동:
${participantContexts.join("\n\n")}

간결한 브리프를 작성하세요:
1. 이 미팅의 맥락 (최근 관련 활동 기반)
2. 참석자별 주요 포인트
3. 논의할 수 있는 주제 제안
4. 미해결 액션 아이템 (있다면)

한국어, [[위키링크]] 유지, 500자 이내.`,
        },
      ],
    });

    return msg.content[0].type === "text" ? msg.content[0].text : buildFallbackBrief(meeting, participantContexts);
  } catch {
    return buildFallbackBrief(meeting, participantContexts);
  }
}

function buildFallbackBrief(
  meeting: UpcomingMeeting,
  contexts: string[]
): string {
  return `## ${meeting.title}

**시간:** ${new Date(meeting.start).toLocaleString("ko-KR")}
**참석자:** ${meeting.participants.join(", ")}
**프로젝트:** ${meeting.project || "미지정"}

## 참석자 컨텍스트
${contexts.join("\n\n")}`;
}

async function main() {
  const meetings = await findUpcomingMeetings();

  if (meetings.length === 0) {
    console.log("[pre-meeting] No meetings in the next 60 minutes");
    return;
  }

  for (const meeting of meetings) {
    // 이미 브리프가 생성되었는지 확인
    const briefId = `brief_${meeting.source_id}`;
    const db = getDb();
    const existing = db
      .prepare("SELECT 1 FROM events WHERE source_id = ?")
      .get(briefId);
    if (existing) continue;

    console.log(`[pre-meeting] Generating brief for: ${meeting.title}`);

    const brief = await generateBrief(meeting);

    // .md 파일로 저장
    const event: OnlimeEvent = {
      id: uuid(),
      timestamp: new Date().toISOString(),
      participants: meeting.participants,
      project: meeting.project || undefined,
      type: "note",
      title: `브리프: ${meeting.title}`,
      body: brief,
      source: "manual",
      source_id: briefId,
      status: "enriched",
      tags: ["brief", "pre-meeting"],
      related: [meeting.source_id],
    };

    const filePath = await writeEventNote(event);
    event.obsidian_path = filePath;

    db.prepare(
      `INSERT OR IGNORE INTO events (id, source, source_id, type, timestamp, title, participants, project, status, obsidian_path, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      event.id, event.source, event.source_id, event.type, event.timestamp,
      event.title, JSON.stringify(event.participants), event.project,
      event.status, event.obsidian_path, new Date().toISOString()
    );

    // 알림
    await notify("Onlime 미팅 브리프", `${meeting.title} (${meeting.participants.join(", ")})`);

    // 텔레그램 푸시 (봇이 설정되어 있으면)
    try {
      const briefMsg =
        `📋 *미팅 브리프*\n\n` +
        `*${meeting.title}*\n` +
        `⏰ ${new Date(meeting.start).toLocaleString("ko-KR")}\n` +
        `👥 ${meeting.participants.join(", ")}\n\n` +
        brief.slice(0, 3000);

      await sendMessage(briefMsg);
    } catch {
      // 텔레그램 미설정 시 무시
    }

    console.log(`[pre-meeting] Brief generated: ${filePath}`);
  }
}

main().catch((err) => {
  console.error("[pre-meeting] Error:", err);
});
