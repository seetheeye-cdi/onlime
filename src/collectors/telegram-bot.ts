/**
 * Onlime 텔레그램 봇 — 원격 제어 인터페이스
 *
 * 기능:
 * - 아침/저녁 브리핑 자동 푸시
 * - 자연어 명령 처리 ("/status", "/brief", 자유 텍스트)
 * - 승인 워크플로우 (인라인 버튼)
 * - 시스템 장애 알림
 *
 * 설정: config/onlime.json에 telegram 섹션 추가
 * {
 *   "telegram": {
 *     "botToken": "123456:ABC-DEF...",
 *     "ownerId": 123456789
 *   }
 * }
 *
 * Telegram Bot API를 직접 사용 (라이브러리 미사용, 의존성 최소화)
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import { generateDailySummary, generateContext } from "../ai/summarizer.js";
import { getDb } from "../db.js";

interface TelegramConfig {
  botToken: string;
  ownerId: number;
}

interface TelegramUpdate {
  update_id: number;
  message?: {
    message_id: number;
    from: { id: number; first_name: string };
    chat: { id: number };
    text?: string;
    date: number;
  };
  callback_query?: {
    id: string;
    from: { id: number };
    message: { chat: { id: number }; message_id: number };
    data: string;
  };
}

let config: TelegramConfig | null = null;
let lastUpdateId = 0;
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function loadTelegramConfig(): Promise<TelegramConfig | null> {
  try {
    const raw = await readFile(
      join(import.meta.dirname, "..", "..", "config", "onlime.json"),
      "utf-8"
    );
    const parsed = JSON.parse(raw);
    if (parsed.telegram?.botToken && parsed.telegram?.ownerId) {
      return parsed.telegram;
    }
  } catch {}
  return null;
}

async function apiCall(method: string, body?: Record<string, unknown>): Promise<any> {
  if (!config) return null;

  const url = `https://api.telegram.org/bot${config.botToken}/${method}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

  const data = await res.json();
  if (!data.ok) {
    console.error(`[telegram] API error (${method}):`, data.description);
  }
  return data;
}

// === 메시지 전송 ===

export async function sendMessage(text: string, options?: {
  parseMode?: "Markdown" | "HTML";
  replyMarkup?: unknown;
}): Promise<void> {
  if (!config) return;

  // 텔레그램 메시지 길이 제한: 4096자
  const chunks = splitMessage(text, 4000);
  for (const chunk of chunks) {
    await apiCall("sendMessage", {
      chat_id: config.ownerId,
      text: chunk,
      parse_mode: options?.parseMode || "Markdown",
      reply_markup: options?.replyMarkup,
    });
  }
}

export async function sendApproval(
  text: string,
  approvalId: string
): Promise<void> {
  await sendMessage(text, {
    replyMarkup: {
      inline_keyboard: [
        [
          { text: "✅ 승인", callback_data: `approve:${approvalId}` },
          { text: "✏️ 수정", callback_data: `edit:${approvalId}` },
          { text: "❌ 거부", callback_data: `reject:${approvalId}` },
        ],
      ],
    },
  });
}

// === 브리핑 푸시 ===

export async function pushMorningBrief(): Promise<void> {
  if (!config) return;

  try {
    const contextPath = join(homedir(), ".onlime", "context", "daily-context.json");
    const raw = await readFile(contextPath, "utf-8");
    const ctx = JSON.parse(raw);

    const today = new Date().toLocaleDateString("ko-KR", {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    });

    let brief = `🌅 *Morning Brief — ${today}*\n\n`;

    if (ctx.upcoming_meetings?.length > 0) {
      brief += `📅 *오늘 일정:*\n`;
      for (const m of ctx.upcoming_meetings) {
        brief += `• ${m}\n`;
      }
      brief += "\n";
    }

    if (ctx.pending_actions?.length > 0) {
      brief += `📋 *미완료 액션:*\n`;
      for (const a of ctx.pending_actions) {
        brief += `• ${a}\n`;
      }
      brief += "\n";
    }

    if (ctx.projects_active?.length > 0) {
      brief += `🎯 *활성 프로젝트:*\n`;
      for (const p of ctx.projects_active) {
        brief += `• ${p}\n`;
      }
    }

    await sendMessage(brief);
  } catch (err) {
    console.error("[telegram] Morning brief error:", err);
    await sendMessage("⚠️ 모닝 브리프 생성 실패. context.json을 확인하세요.");
  }
}

export async function pushDailySummary(): Promise<void> {
  if (!config) return;

  try {
    const summary = await generateDailySummary();
    await sendMessage(`🌙 *Daily Summary*\n\n${summary}`);
  } catch (err) {
    console.error("[telegram] Daily summary push error:", err);
  }
}

export async function pushAlert(message: string): Promise<void> {
  if (!config) return;
  await sendMessage(`⚠️ *Onlime Alert*\n\n${message}`);
}

// === 명령 처리 ===

async function handleMessage(text: string, chatId: number): Promise<void> {
  const cmd = text.trim().toLowerCase();

  if (cmd === "/start" || cmd === "/help") {
    await sendMessage(
      `🤖 *Onlime AI Assistant*\n\n` +
        `명령어:\n` +
        `/brief — 오늘의 브리핑\n` +
        `/summary — 일일 요약 (최신)\n` +
        `/status — 시스템 상태\n` +
        `/people — 최근 접촉한 사람\n` +
        `/projects — 프로젝트 현황\n\n` +
        `자유 텍스트로도 질문할 수 있어요.`
    );
    return;
  }

  if (cmd === "/brief") {
    await pushMorningBrief();
    return;
  }

  if (cmd === "/summary") {
    await sendMessage("⏳ 요약 생성 중...");
    const summary = await generateDailySummary();
    await sendMessage(summary);
    return;
  }

  if (cmd === "/status") {
    const db = getDb();
    const eventCount = (db.prepare("SELECT COUNT(*) as c FROM events").get() as any).c;
    const peopleCount = (db.prepare("SELECT COUNT(*) as c FROM people").get() as any).c;
    const projectCount = (db.prepare("SELECT COUNT(*) as c FROM projects").get() as any).c;

    const lastHealth = db
      .prepare("SELECT source, status, checked_at FROM health_checks ORDER BY checked_at DESC LIMIT 5")
      .all() as Array<{ source: string; status: string; checked_at: string }>;

    let status = `📊 *Onlime 시스템 상태*\n\n`;
    status += `이벤트: ${eventCount}건\n`;
    status += `People: ${peopleCount}명\n`;
    status += `Projects: ${projectCount}개\n\n`;

    if (lastHealth.length > 0) {
      status += `*최근 헬스 체크:*\n`;
      for (const h of lastHealth) {
        const icon = h.status === "ok" ? "✅" : h.status === "warning" ? "⚠️" : "❌";
        status += `${icon} ${h.source} (${h.checked_at})\n`;
      }
    }

    await sendMessage(status);
    return;
  }

  if (cmd === "/people") {
    const db = getDb();
    const recent = db
      .prepare(
        `SELECT name, wikilink, last_contact, interaction_count
         FROM people WHERE last_contact IS NOT NULL
         ORDER BY last_contact DESC LIMIT 10`
      )
      .all() as Array<{
      name: string;
      wikilink: string;
      last_contact: string;
      interaction_count: number;
    }>;

    let msg = `👥 *최근 접촉한 사람 (Top 10)*\n\n`;
    for (const p of recent) {
      msg += `• ${p.name} — ${p.last_contact} (${p.interaction_count}회)\n`;
    }

    await sendMessage(msg || "아직 접촉 기록이 없습니다.");
    return;
  }

  if (cmd === "/projects") {
    const db = getDb();
    const projects = db
      .prepare("SELECT name, keywords FROM projects WHERE active = 1")
      .all() as Array<{ name: string; keywords: string }>;

    let msg = `📁 *활성 프로젝트*\n\n`;
    for (const p of projects) {
      msg += `• ${p.name}\n`;
    }

    await sendMessage(msg);
    return;
  }

  // 자유 텍스트 — 간단한 응답 (Phase 3에서 claude -p 연동)
  await sendMessage(
    `📝 "${text}" 수신.\n\n` +
      `자연어 명령 처리는 Phase 3에서 OpenClaw/Claude 연동 후 활성화됩니다.\n` +
      `현재 사용 가능한 명령: /help`
  );
}

async function handleCallback(callbackId: string, data: string): Promise<void> {
  const [action, approvalId] = data.split(":");

  await apiCall("answerCallbackQuery", {
    callback_query_id: callbackId,
    text: action === "approve" ? "✅ 승인됨" : action === "reject" ? "❌ 거부됨" : "✏️ 수정 모드",
  });

  // Phase 3에서 실제 승인 워크플로우 연결
  console.log(`[telegram] Callback: ${action} for ${approvalId}`);

  if (action === "approve") {
    await sendMessage(`✅ 승인 완료: ${approvalId}`);
  } else if (action === "reject") {
    await sendMessage(`❌ 거부됨: ${approvalId}`);
  }
}

// === 폴링 루프 ===

async function pollUpdates(): Promise<void> {
  if (!config) return;

  try {
    const data = await apiCall("getUpdates", {
      offset: lastUpdateId + 1,
      timeout: 5,
      allowed_updates: ["message", "callback_query"],
    });

    if (!data?.result) return;

    for (const update of data.result as TelegramUpdate[]) {
      lastUpdateId = update.update_id;

      // 소유자만 응답
      const userId =
        update.message?.from?.id || update.callback_query?.from?.id;
      if (userId !== config.ownerId) {
        console.log(`[telegram] Unauthorized access from user ${userId}`);
        continue;
      }

      if (update.message?.text) {
        await handleMessage(update.message.text, update.message.chat.id);
      }

      if (update.callback_query) {
        await handleCallback(
          update.callback_query.id,
          update.callback_query.data
        );
      }
    }
  } catch (err) {
    // 네트워크 에러는 조용히 무시 (다음 폴에서 재시도)
    if (String(err).includes("fetch")) return;
    console.error("[telegram] Poll error:", err);
  }
}

// === 시작/중지 ===

export async function startTelegramBot(): Promise<boolean> {
  config = await loadTelegramConfig();

  if (!config) {
    console.log("[telegram] Bot not configured. Add telegram section to config/onlime.json:");
    console.log('  "telegram": { "botToken": "...", "ownerId": 123456789 }');
    return false;
  }

  // 봇 정보 확인
  const me = await apiCall("getMe");
  if (me?.result) {
    console.log(`[telegram] Bot started: @${me.result.username}`);
  }

  // 2초 간격 long-polling
  pollTimer = setInterval(pollUpdates, 2000);

  return true;
}

export function stopTelegramBot(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  config = null;
}

function splitMessage(text: string, maxLen: number): string[] {
  if (text.length <= maxLen) return [text];
  const chunks: string[] = [];
  let remaining = text;
  while (remaining.length > 0) {
    if (remaining.length <= maxLen) {
      chunks.push(remaining);
      break;
    }
    // 줄바꿈 위치에서 분할
    let splitAt = remaining.lastIndexOf("\n", maxLen);
    if (splitAt <= 0) splitAt = maxLen;
    chunks.push(remaining.slice(0, splitAt));
    remaining = remaining.slice(splitAt);
  }
  return chunks;
}
