import { google } from "googleapis";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import { v4 as uuid } from "uuid";
import { OAuth2Client } from "google-auth-library";
import type { OnlimeEvent, OnlimeConfig } from "../types.js";
import { getCursor, setCursor, insertEvent, eventExists } from "../db.js";
import { writeEventNote } from "../writer.js";
import { enrichEvent } from "../enricher.js";
import { notify } from "../notify.js";

const CREDENTIALS_PATH = join(homedir(), ".onlime", "google-credentials.json");
const TOKEN_PATH = join(homedir(), ".onlime", "google-token.json");

async function getAuthClient(): Promise<OAuth2Client | null> {
  try {
    const credRaw = await readFile(CREDENTIALS_PATH, "utf-8");
    const credentials = JSON.parse(credRaw);
    const { client_id, client_secret, redirect_uris } =
      credentials.installed || credentials.web;

    const oauth2 = new OAuth2Client(client_id, client_secret, redirect_uris?.[0]);

    const tokenRaw = await readFile(TOKEN_PATH, "utf-8");
    const token = JSON.parse(tokenRaw);
    oauth2.setCredentials(token);

    oauth2.on("tokens", async (newTokens) => {
      const existing = JSON.parse(await readFile(TOKEN_PATH, "utf-8"));
      const merged = { ...existing, ...newTokens };
      await writeFile(TOKEN_PATH, JSON.stringify(merged, null, 2));
    });

    return oauth2;
  } catch {
    console.log("[gcal] Google auth not configured. Run gmail-auth.ts first.");
    return null;
  }
}

function todayStart(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function todayEnd(): string {
  const d = new Date();
  d.setHours(23, 59, 59, 999);
  return d.toISOString();
}

export async function collectGcal(config: OnlimeConfig): Promise<number> {
  const auth = await getAuthClient();
  if (!auth) return 0;

  const calendar = google.calendar({ version: "v3", auth });
  let totalNew = 0;

  try {
    // 오늘 + 내일의 이벤트 수집
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(23, 59, 59, 999);

    const res = await calendar.events.list({
      calendarId: "primary",
      timeMin: todayStart(),
      timeMax: tomorrow.toISOString(),
      singleEvents: true,
      orderBy: "startTime",
      timeZone: "Asia/Seoul",
    });

    const events = res.data.items || [];

    for (const gcalEvent of events) {
      if (!gcalEvent.id) continue;
      const sourceId = `gcal_${gcalEvent.id}`;

      // 이미 수집된 이벤트 스킵 (새 이벤트만)
      if (eventExists("gcal", sourceId)) continue;

      // 거부한 이벤트 스킵
      const myStatus = gcalEvent.attendees?.find((a) => a.self)?.responseStatus;
      if (myStatus === "declined") continue;

      const start = gcalEvent.start?.dateTime || gcalEvent.start?.date || "";
      const end = gcalEvent.end?.dateTime || gcalEvent.end?.date || "";
      const title = gcalEvent.summary || "(제목 없음)";
      const location = gcalEvent.location || "";
      const description = gcalEvent.description || "";

      // 참석자 추출
      const participants: string[] = [];
      if (gcalEvent.attendees) {
        for (const att of gcalEvent.attendees) {
          if (att.self) continue; // 자기 자신 제외
          const name = att.displayName || att.email?.split("@")[0] || "Unknown";
          participants.push(name);
        }
      }

      // 이벤트 본문 구성
      const bodyParts = [`# ${title}`, ""];
      bodyParts.push(`**시간:** ${formatTime(start)} - ${formatTime(end)}`);
      if (location) bodyParts.push(`**장소:** ${location}`);
      if (participants.length > 0)
        bodyParts.push(`**참석자:** ${participants.join(", ")}`);
      if (gcalEvent.htmlLink)
        bodyParts.push(`**캘린더:** [열기](${gcalEvent.htmlLink})`);
      if (description) {
        bodyParts.push("", "## 설명", description.slice(0, 1000));
      }

      let event: OnlimeEvent = {
        id: uuid(),
        timestamp: start ? new Date(start).toISOString() : new Date().toISOString(),
        participants,
        type: "calendar",
        title,
        body: bodyParts.join("\n"),
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
    }

    // 커서: 마지막 sync 시간
    setCursor("gcal", new Date().toISOString());
  } catch (err) {
    console.error("[gcal] Collection error:", err);
  }

  if (totalNew > 0) {
    await notify("Onlime 캘린더", `${totalNew}건 수집 완료`);
    console.log(`[gcal] Collected ${totalNew} new events`);
  }

  return totalNew;
}

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
