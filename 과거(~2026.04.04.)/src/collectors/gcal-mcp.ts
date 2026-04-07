/**
 * Google Calendar MCP Collector — claude -p로 일정 수집
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { v4 as uuid } from "uuid";
import type { OnlimeEvent, OnlimeConfig } from "../types.js";
import { insertEvent, eventExists } from "../db.js";
import { writeEventNote } from "../writer.js";
import { enrichEvent } from "../enricher.js";
import { notify } from "../notify.js";

const exec = promisify(execFile);

interface McpCalEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  location?: string;
  attendees?: string[];
  description?: string;
}

async function fetchCalendarViaMcp(): Promise<McpCalEvent[]> {
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  const timeMin = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}T00:00:00`;
  const timeMax = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, "0")}-${String(tomorrow.getDate()).padStart(2, "0")}T23:59:59`;

  try {
    const prompt = `List my Google Calendar events from ${timeMin} to ${timeMax} (timezone: Asia/Seoul, condenseEventDetails: false).
For each event, output ONLY a JSON array with this format, no other text:
[{"id":"event_id","summary":"title","start":"ISO datetime","end":"ISO datetime","location":"place","attendees":["name1","name2"],"description":"desc"}]

If no events, output: []`;

    const { stdout } = await exec(
      "claude",
      [
        "-p", prompt,
        "--allowedTools", "mcp__claude_ai_Google_Calendar__gcal_list_events",
        "--output-format", "text",
      ],
      { timeout: 120_000, env: { ...process.env, LANG: "en_US.UTF-8" } }
    );

    const jsonMatch = stdout.match(/\[[\s\S]*\]/);
    if (!jsonMatch) return [];

    const parsed = JSON.parse(jsonMatch[0]);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.error("[gcal-mcp] claude -p failed:", err);
    return [];
  }
}

export async function collectGcalMcp(_config: OnlimeConfig): Promise<number> {
  console.log("[gcal-mcp] Fetching calendar events...");
  const events = await fetchCalendarViaMcp();
  let totalNew = 0;

  for (const cal of events) {
    if (!cal.id) continue;

    const sourceId = `gcal_${cal.id}`;
    if (eventExists("gcal", sourceId)) continue;

    const participants = (cal.attendees || []).filter(a => a && !a.includes("cdiseetheeye"));

    let event: OnlimeEvent = {
      id: uuid(),
      timestamp: cal.start ? new Date(cal.start).toISOString() : new Date().toISOString(),
      participants,
      type: "calendar",
      title: cal.summary || "(제목 없음)",
      body: [
        `# ${cal.summary || "(제목 없음)"}`,
        "",
        `**시간:** ${formatKoreanTime(cal.start)} - ${formatKoreanTime(cal.end)}`,
        cal.location ? `**장소:** ${cal.location}` : "",
        participants.length > 0 ? `**참석자:** ${participants.join(", ")}` : "",
        "",
        cal.description ? `## 설명\n${cal.description.slice(0, 1000)}` : "",
      ].filter(Boolean).join("\n"),
      source: "gcal",
      source_id: sourceId,
      status: "raw",
      tags: [],
      related: [],
    };

    event = enrichEvent(event);
    const filePath = await writeEventNote(event);
    event.obsidian_path = filePath;
    insertEvent(event);
    totalNew++;

    console.log(`[gcal-mcp] 📅 ${cal.summary} (${formatKoreanTime(cal.start)})`);
  }

  if (totalNew > 0) {
    await notify("Onlime 캘린더", `${totalNew}건 수집`);
  }

  return totalNew;
}

function formatKoreanTime(iso: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
  } catch {
    return iso;
  }
}
