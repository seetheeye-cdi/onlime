import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createHash } from "node:crypto";
import type { KakaoChat, KakaoMessage, ChatState } from "./types.js";
import { appendToDaily } from "./obsidian-writer.js";

const exec = promisify(execFile);

const STATE_PATH = join(import.meta.dirname, "..", "config", "state.json");

async function loadState(): Promise<ChatState> {
  try {
    const raw = await readFile(STATE_PATH, "utf-8");
    return JSON.parse(raw);
  } catch {
    return { lastChecked: new Date(0).toISOString(), lastMessages: {} };
  }
}

async function saveState(state: ChatState): Promise<void> {
  await writeFile(STATE_PATH, JSON.stringify(state, null, 2));
}

function messageHash(msg: KakaoMessage): string {
  return createHash("md5")
    .update(`${msg.author}|${msg.time_raw}|${msg.body}`)
    .digest("hex");
}

async function listChats(limit: number): Promise<string[]> {
  try {
    const { stdout, stderr } = await exec(
      "kmsg",
      ["chats", "--limit", String(limit), "--verbose"],
      { timeout: 30_000 }
    );
    const output = stdout || stderr;
    const chatNames: string[] = [];

    // kmsg chats --verbose output format:
    // [1] ChatName
    //     └─ last message preview
    // [2] ChatName
    //     └─ ...
    // We also handle plain format: [N] ChatName
    for (const line of output.split("\n")) {
      // Match lines like "[1] 테크노크라츠 유민승" or "[2] 오전 11:08"
      const match = line.match(/^\[(\d+)\]\s+(.+)$/);
      if (match) {
        const name = match[2].trim();
        // Skip entries that are just times (no chat name available)
        // or "(Unknown Chat)" - these can't be read by kmsg read
        if (name !== "(Unknown Chat)" && !/^오[전후]\s+\d+:\d+$/.test(name)) {
          chatNames.push(name);
        }
      }
    }

    return chatNames;
  } catch (err) {
    console.error("[kakao-monitor] Failed to list chats:", err);
    return [];
  }
}

async function readChat(
  chatName: string,
  limit: number
): Promise<KakaoChat | null> {
  try {
    const { stdout } = await exec(
      "kmsg",
      ["read", chatName, "--limit", String(limit), "--json"],
      { timeout: 30_000 }
    );
    return JSON.parse(stdout) as KakaoChat;
  } catch (err) {
    console.error(`[kakao-monitor] Failed to read chat "${chatName}":`, err);
    return null;
  }
}

export async function pollKakaoMessages(config: {
  maxChats: number;
  maxMessagesPerChat: number;
  excludeChats: string[];
  dailyNotePath: string;
  watchChats?: string[];
}): Promise<void> {
  const state = await loadState();

  // Try to get chat list from kmsg; fall back to watchChats config
  let chatNames = await listChats(config.maxChats);
  if (chatNames.length === 0 && config.watchChats && config.watchChats.length > 0) {
    console.log("[kakao-monitor] Using watchChats from config");
    chatNames = config.watchChats;
  }

  if (chatNames.length === 0) {
    console.log("[kakao-monitor] No chats found. Add chat names to config/chats.json watchChats array.");
    return;
  }

  const newMessagesByChat: Record<string, KakaoMessage[]> = {};
  const newState: ChatState = {
    lastChecked: new Date().toISOString(),
    lastMessages: { ...state.lastMessages },
  };

  for (const chatName of chatNames) {
    if (config.excludeChats.some((ex) => chatName.includes(ex))) {
      continue;
    }

    const chatData = await readChat(chatName, config.maxMessagesPerChat);
    if (!chatData || chatData.messages.length === 0) continue;

    const lastKnownHash = state.lastMessages[chatName];
    const messages = chatData.messages;

    // Find new messages by comparing hashes
    let newMessages: KakaoMessage[];
    if (!lastKnownHash) {
      // First time seeing this chat - take all messages
      newMessages = messages;
    } else {
      // Find the index of the last known message
      const lastIdx = messages.findIndex(
        (m) => messageHash(m) === lastKnownHash
      );
      if (lastIdx === -1) {
        // Last known message not found, take all messages
        newMessages = messages;
      } else {
        // Take only messages after the last known one
        newMessages = messages.slice(lastIdx + 1);
      }
    }

    if (newMessages.length > 0) {
      newMessagesByChat[chatName] = newMessages;
      // Update state with hash of the latest message
      const latest = messages[messages.length - 1];
      newState.lastMessages[chatName] = messageHash(latest);
    }
  }

  // Write new messages to Obsidian daily note
  const totalNew = Object.values(newMessagesByChat).reduce(
    (sum, msgs) => sum + msgs.length,
    0
  );

  if (totalNew > 0) {
    console.log(
      `[kakao-monitor] Found ${totalNew} new messages across ${Object.keys(newMessagesByChat).length} chats`
    );
    await appendToDaily(newMessagesByChat, config.dailyNotePath);
  } else {
    console.log("[kakao-monitor] No new messages");
  }

  await saveState(newState);
}

// Allow running standalone
if (process.argv[1]?.endsWith("kakao-monitor.ts") || process.argv[1]?.endsWith("kakao-monitor.js")) {
  const config: {
    maxChats: number;
    maxMessagesPerChat: number;
    excludeChats: string[];
    dailyNotePath: string;
    watchChats: string[];
  } = {
    maxChats: 50,
    maxMessagesPerChat: 30,
    excludeChats: [],
    dailyNotePath: "/Users/aiparty/Desktop/Obsidian_sinc/2. OUTPUT/Daily",
    watchChats: [],
  };

  try {
    const chatsJson = await readFile(
      join(import.meta.dirname, "..", "config", "chats.json"),
      "utf-8"
    );
    const chatsConfig = JSON.parse(chatsJson);
    if (chatsConfig.exclude) config.excludeChats = chatsConfig.exclude;
    if (chatsConfig.dailyNotePath) config.dailyNotePath = chatsConfig.dailyNotePath;
    if (chatsConfig.watchChats) config.watchChats = chatsConfig.watchChats;
  } catch {
    // Use defaults
  }

  pollKakaoMessages(config).catch(console.error);
}
