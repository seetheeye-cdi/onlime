import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { createHash } from "node:crypto";
import { v4 as uuid } from "uuid";
import type { KakaoChat, KakaoMessage, OnlimeEvent, OnlimeConfig } from "../types.js";
import { getCursor, setCursor, insertEvent, eventExists } from "../db.js";
import { writeEventNote } from "../writer.js";
import { enrichEvent } from "../enricher.js";
import { notify } from "../notify.js";

const exec = promisify(execFile);

function messageHash(msg: KakaoMessage): string {
  return createHash("md5")
    .update(`${msg.author}|${msg.time_raw}|${msg.body}`)
    .digest("hex");
}

function batchHash(messages: KakaoMessage[]): string {
  return createHash("md5")
    .update(messages.map((m) => `${m.author}|${m.time_raw}|${m.body}`).join("\n"))
    .digest("hex");
}

async function listChats(limit: number): Promise<string[]> {
  try {
    const { stdout, stderr } = await exec("kmsg", ["chats", "--limit", String(limit), "--verbose"], {
      timeout: 30_000,
    });
    const output = stdout || stderr;
    const chatNames: string[] = [];
    for (const line of output.split("\n")) {
      const match = line.match(/^\[(\d+)\]\s+(.+)$/);
      if (match) {
        const name = match[2].trim();
        if (name !== "(Unknown Chat)" && !/^오[전후]\s+\d+:\d+$/.test(name)) {
          chatNames.push(name);
        }
      }
    }
    return chatNames;
  } catch (err) {
    console.error("[kakao] Failed to list chats:", err);
    return [];
  }
}

async function readChat(chatName: string, limit: number): Promise<KakaoChat | null> {
  try {
    const { stdout } = await exec("kmsg", ["read", chatName, "--limit", String(limit), "--json"], {
      timeout: 30_000,
    });
    return JSON.parse(stdout) as KakaoChat;
  } catch (err) {
    console.error(`[kakao] Failed to read "${chatName}":`, err);
    return null;
  }
}

function todayDate(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

export async function collectKakao(config: OnlimeConfig): Promise<number> {
  let chatNames = await listChats(50);

  if (chatNames.length === 0 && config.watchChats.length > 0) {
    chatNames = config.watchChats;
  }

  if (chatNames.length === 0) {
    console.log("[kakao] No chats found");
    return 0;
  }

  let totalNew = 0;

  for (const chatName of chatNames) {
    if (config.excludeChats.some((ex) => chatName.includes(ex))) continue;

    const chatData = await readChat(chatName, 30);
    if (!chatData || chatData.messages.length === 0) continue;

    const cursorKey = `kakao:${chatName}`;
    const lastHash = getCursor(cursorKey);
    const messages = chatData.messages;

    // 새 메시지 찾기
    let newMessages: KakaoMessage[];
    if (!lastHash) {
      newMessages = messages;
    } else {
      const lastIdx = messages.findIndex((m) => messageHash(m) === lastHash);
      if (lastIdx === -1) {
        newMessages = messages;
      } else {
        newMessages = messages.slice(lastIdx + 1);
      }
    }

    if (newMessages.length === 0) continue;

    // 소스 ID = 채팅방 + 날짜 + 배치 해시 (같은 채팅방 같은 날짜에 여러 배치 가능)
    const batch = batchHash(newMessages);
    const sourceId = `kakao_${chatName.replace(/\s+/g, "")}_${todayDate()}_${batch.slice(0, 8)}`;

    // 이미 처리된 배치면 스킵
    if (eventExists("kakao", sourceId)) {
      // 커서만 업데이트
      const latest = messages[messages.length - 1];
      setCursor(cursorKey, messageHash(latest));
      continue;
    }

    // 메시지 본문 구성
    const bodyLines = newMessages.map(
      (msg) => `- **${msg.time_raw}** ${msg.author}: ${msg.body}`
    );

    // 참여자 추출 (고유 작성자)
    const authors = [...new Set(newMessages.map((m) => m.author))];

    // OnlimeEvent 생성
    let event: OnlimeEvent = {
      id: uuid(),
      timestamp: nowIso(),
      participants: authors, // enricher가 [[위키링크]]로 변환
      project: undefined, // enricher가 매칭
      type: "chat",
      title: chatName,
      body: `# ${chatName} — ${todayDate()}\n\n${bodyLines.join("\n")}`,
      source: "kakao",
      source_id: sourceId,
      status: "raw",
      tags: [],
      related: [],
    };

    // Enrichment (사람/프로젝트 매칭)
    event = enrichEvent(event);

    // .md 파일 생성
    const filePath = await writeEventNote(event);
    event.obsidian_path = filePath;

    // SQLite에 인덱싱
    insertEvent(event);

    // 커서 업데이트
    const latest = messages[messages.length - 1];
    setCursor(cursorKey, messageHash(latest));

    totalNew += newMessages.length;
    console.log(`[kakao] ${chatName}: ${newMessages.length} new messages → ${filePath}`);
  }

  // Heartbeat 알림
  if (totalNew > 0) {
    await notify("Onlime 카카오톡", `${totalNew}건 수집 완료`);
  }

  return totalNew;
}
