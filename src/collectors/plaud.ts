import { watch } from "chokidar";
import { readFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { v4 as uuid } from "uuid";
import matter from "gray-matter";
import type { OnlimeEvent, OnlimeConfig } from "../types.js";
import { insertEvent, eventExists } from "../db.js";
import { writeEventNote } from "../writer.js";
import { enrichEvent } from "../enricher.js";
import { notify } from "../notify.js";

// Plaud 동기화 폴더 후보 경로
const PLAUD_WATCH_PATHS = [
  join(process.env.HOME || "", "Documents", "Plaud"),
  join(process.env.HOME || "", "Library", "Mobile Documents", "com~apple~CloudDocs", "Plaud"),
  join(process.env.HOME || "", "Desktop", "Plaud"),
];

let watcher: ReturnType<typeof watch> | null = null;

export async function startPlaudWatcher(_config: OnlimeConfig): Promise<void> {
  // 존재하는 첫 번째 경로 사용
  const { accessSync } = await import("node:fs");
  const watchPath = PLAUD_WATCH_PATHS.find((p) => {
    try {
      accessSync(p);
      return true;
    } catch {
      return false;
    }
  });

  if (!watchPath) {
    console.log("[plaud] No Plaud sync folder found. Checked:", PLAUD_WATCH_PATHS.join(", "));
    console.log("[plaud] Create one of these folders or configure in onlime.json");
    return;
  }

  console.log(`[plaud] Watching: ${watchPath}`);

  watcher = watch(watchPath, {
    ignored: /(^|[\/\\])\../, // 숨김 파일 제외
    persistent: true,
    ignoreInitial: true, // 기존 파일 무시, 새 파일만
    awaitWriteFinish: {
      stabilityThreshold: 3000, // 3초간 변경 없으면 완료로 판단
      pollInterval: 500,
    },
  });

  watcher.on("add", async (filePath) => {
    const ext = filePath.split(".").pop()?.toLowerCase();
    if (!["txt", "md", "srt", "docx"].includes(ext || "")) return;

    console.log(`[plaud] New file detected: ${basename(filePath)}`);

    try {
      await processPlaudFile(filePath);
    } catch (err) {
      console.error(`[plaud] Error processing ${filePath}:`, err);
    }
  });

  watcher.on("error", (err) => {
    console.error("[plaud] Watcher error:", err);
  });
}

export function stopPlaudWatcher(): void {
  watcher?.close();
  watcher = null;
}

async function processPlaudFile(filePath: string): Promise<void> {
  const filename = basename(filePath);
  const sourceId = `plaud_${filename}`;

  if (eventExists("plaud", sourceId)) return;

  const raw = await readFile(filePath, "utf-8");

  // Plaud 텍스트 파일에서 메타데이터 추출 시도
  const { title, participants, timestamp } = extractPlaudMetadata(filename, raw);

  let event: OnlimeEvent = {
    id: uuid(),
    timestamp,
    participants,
    type: "meeting",
    title,
    body: `# ${title}\n\n## 트랜스크립트\n\n${raw.slice(0, 10000)}`, // 10K자 제한
    source: "plaud",
    source_id: sourceId,
    status: "raw",
    tags: ["meeting", "transcript"],
    related: [],
  };

  event = enrichEvent(event);
  const notePath = await writeEventNote(event);
  event.obsidian_path = notePath;
  insertEvent(event);

  await notify("Onlime Plaud", `회의록 수집: ${title}`);
  console.log(`[plaud] Processed: ${filename} → ${notePath}`);
}

function extractPlaudMetadata(
  filename: string,
  content: string
): { title: string; participants: string[]; timestamp: string } {
  // Plaud 파일명 패턴: "2026-03-18 14-30 미팅 제목.txt" 또는 유사
  const dateMatch = filename.match(/(\d{4}[-_]\d{2}[-_]\d{2})/);
  const timeMatch = filename.match(/(\d{2}[-_]\d{2})(?:\s|[-_])/);

  let timestamp: string;
  if (dateMatch) {
    const dateStr = dateMatch[1].replace(/_/g, "-");
    const timeStr = timeMatch ? timeMatch[1].replace(/_/g, ":") + ":00" : "00:00:00";
    timestamp = new Date(`${dateStr}T${timeStr}`).toISOString();
  } else {
    timestamp = new Date().toISOString();
  }

  // 제목: 날짜/시간 부분 제거
  const title =
    filename
      .replace(/\.\w+$/, "") // 확장자 제거
      .replace(/\d{4}[-_]\d{2}[-_]\d{2}/, "") // 날짜 제거
      .replace(/\d{2}[-_]\d{2}/, "") // 시간 제거
      .replace(/^[-_\s]+|[-_\s]+$/g, "") // 앞뒤 정리
      .trim() || "회의록";

  // 참여자: 트랜스크립트에서 화자 레이블 추출
  // 패턴: "Speaker 1:", "화자 1:", "유민승:", "[유민승]" 등
  const speakers = new Set<string>();
  const speakerPatterns = [
    /^([가-힣a-zA-Z\s]+)\s*:/gm, // "이름:"
    /^\[([가-힣a-zA-Z\s]+)\]/gm, // "[이름]"
    /^Speaker\s*(\d+)/gim, // "Speaker 1"
    /^화자\s*(\d+)/gm, // "화자 1"
  ];

  for (const pattern of speakerPatterns) {
    let match;
    while ((match = pattern.exec(content)) !== null) {
      const speaker = match[1].trim();
      if (speaker && speaker.length < 20 && speaker.length > 1) {
        speakers.add(speaker);
      }
    }
  }

  return {
    title,
    participants: [...speakers].slice(0, 10),
    timestamp,
  };
}
