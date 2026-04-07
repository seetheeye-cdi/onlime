import { google } from "googleapis";
import { readFile, writeFile, mkdir } from "node:fs/promises";
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

// 수집 제외 패턴
const SKIP_SENDERS = [/noreply/i, /no-reply/i, /notifications?@/i, /mailer-daemon/i];
const SKIP_SUBJECTS = [/보안\s*코드/i, /security\s*code/i, /로그인/i, /verify/i, /인증번호/i];
const SKIP_CATEGORIES = ["promotions", "social", "updates", "forums"];

async function getAuthClient(): Promise<OAuth2Client | null> {
  try {
    const credRaw = await readFile(CREDENTIALS_PATH, "utf-8");
    const credentials = JSON.parse(credRaw);
    const { client_id, client_secret, redirect_uris } =
      credentials.installed || credentials.web;

    const oauth2 = new OAuth2Client(client_id, client_secret, redirect_uris?.[0]);

    try {
      const tokenRaw = await readFile(TOKEN_PATH, "utf-8");
      const token = JSON.parse(tokenRaw);
      oauth2.setCredentials(token);

      // 토큰 자동 갱신
      oauth2.on("tokens", async (newTokens) => {
        const existing = JSON.parse(await readFile(TOKEN_PATH, "utf-8"));
        const merged = { ...existing, ...newTokens };
        await writeFile(TOKEN_PATH, JSON.stringify(merged, null, 2));
        console.log("[gmail] Token refreshed");
      });

      return oauth2;
    } catch {
      console.log("[gmail] No token found. Run 'npx tsx src/scripts/gmail-auth.ts' first.");
      return null;
    }
  } catch {
    console.log("[gmail] No credentials found at", CREDENTIALS_PATH);
    console.log("[gmail] Download OAuth credentials from Google Cloud Console");
    console.log("[gmail] Save as ~/.onlime/google-credentials.json");
    return null;
  }
}

function shouldSkipEmail(from: string, subject: string, labels: string[]): boolean {
  if (SKIP_SENDERS.some((re) => re.test(from))) return true;
  if (SKIP_SUBJECTS.some((re) => re.test(subject))) return true;
  if (labels.some((l) => SKIP_CATEGORIES.includes(l.toLowerCase()))) return true;
  return false;
}

function extractPlainText(payload: any): string {
  if (!payload) return "";

  // 단순 텍스트
  if (payload.mimeType === "text/plain" && payload.body?.data) {
    return Buffer.from(payload.body.data, "base64").toString("utf-8");
  }

  // 멀티파트
  if (payload.parts) {
    for (const part of payload.parts) {
      if (part.mimeType === "text/plain" && part.body?.data) {
        return Buffer.from(part.body.data, "base64").toString("utf-8");
      }
    }
    // 중첩 멀티파트
    for (const part of payload.parts) {
      const text = extractPlainText(part);
      if (text) return text;
    }
  }

  return "";
}

function extractHeader(headers: Array<{ name?: string | null; value?: string | null }>, name: string): string {
  return headers?.find((h) => h.name?.toLowerCase() === name.toLowerCase())?.value || "";
}

export async function collectGmail(config: OnlimeConfig): Promise<number> {
  const auth = await getAuthClient();
  if (!auth) return 0;

  const gmail = google.gmail({ version: "v1", auth });
  let totalNew = 0;

  try {
    // historyId 기반 증분 수집 또는 최근 메시지 폴링
    const cursor = getCursor("gmail");

    let messageIds: string[] = [];

    if (cursor) {
      // 증분: history API 사용
      try {
        const historyRes = await gmail.users.history.list({
          userId: "me",
          startHistoryId: cursor,
          historyTypes: ["messageAdded"],
        });

        const histories = historyRes.data.history || [];
        for (const h of histories) {
          if (h.messagesAdded) {
            for (const m of h.messagesAdded) {
              if (m.message?.id) messageIds.push(m.message.id);
            }
          }
        }

        // 새 historyId 저장
        if (historyRes.data.historyId) {
          setCursor("gmail", historyRes.data.historyId);
        }
      } catch (err: any) {
        if (err?.code === 404) {
          // historyId 만료 — 전체 폴링으로 폴백
          console.log("[gmail] History expired, falling back to full poll");
          messageIds = await pollRecentMessages(gmail);
        } else {
          throw err;
        }
      }
    } else {
      // 초기: 최근 메시지 폴링
      messageIds = await pollRecentMessages(gmail);
    }

    // 중복 제거
    messageIds = [...new Set(messageIds)];

    for (const msgId of messageIds) {
      if (eventExists("gmail", `gmail_${msgId}`)) continue;

      try {
        const msgRes = await gmail.users.messages.get({
          userId: "me",
          id: msgId,
          format: "full",
        });

        const msg = msgRes.data;
        const headers = msg.payload?.headers || [];
        const from = extractHeader(headers, "From");
        const subject = extractHeader(headers, "Subject");
        const date = extractHeader(headers, "Date");
        const to = extractHeader(headers, "To");
        const labels = msg.labelIds || [];

        // 필터링
        if (shouldSkipEmail(from, subject, labels)) continue;

        // 본문 추출
        const body = extractPlainText(msg.payload);
        const truncatedBody = body.slice(0, 2000); // 토큰 절약

        // 참여자 추출
        const participants: string[] = [];
        const fromName = from.match(/^(.+?)\s*</)
          ? from.match(/^(.+?)\s*</)![1].replace(/"/g, "")
          : from.split("@")[0];
        participants.push(fromName);

        let event: OnlimeEvent = {
          id: uuid(),
          timestamp: date ? new Date(date).toISOString() : new Date().toISOString(),
          participants,
          type: "email",
          title: subject || "(제목 없음)",
          body: `# ${subject}\n\n**From:** ${from}\n**To:** ${to}\n**Date:** ${date}\n\n${truncatedBody}`,
          source: "gmail",
          source_id: `gmail_${msgId}`,
          status: "raw",
          tags: labels.filter((l) => !l.startsWith("CATEGORY_")),
          related: [],
        };

        event = enrichEvent(event);
        const filePath = await writeEventNote(event);
        event.obsidian_path = filePath;
        insertEvent(event);
        totalNew++;
      } catch (err) {
        console.error(`[gmail] Error processing message ${msgId}:`, err);
      }
    }

    // historyId 초기 설정
    if (!cursor) {
      const profile = await gmail.users.getProfile({ userId: "me" });
      if (profile.data.historyId) {
        setCursor("gmail", profile.data.historyId);
      }
    }
  } catch (err) {
    console.error("[gmail] Collection error:", err);
  }

  if (totalNew > 0) {
    await notify("Onlime Gmail", `${totalNew}건 수집 완료`);
    console.log(`[gmail] Collected ${totalNew} new emails`);
  }

  return totalNew;
}

async function pollRecentMessages(gmail: any): Promise<string[]> {
  const res = await gmail.users.messages.list({
    userId: "me",
    maxResults: 20,
    q: "newer_than:1h is:inbox -category:promotions -category:social",
  });

  return (res.data.messages || []).map((m: any) => m.id);
}
