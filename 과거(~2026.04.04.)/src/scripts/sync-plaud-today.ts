// Plaud API에서 오늘의 녹음을 가져와 Obsidian Meeting 노트 생성
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import { v4 as uuid } from "uuid";
import { getDb } from "../db.js";
import { insertEvent, eventExists } from "../db.js";
import { writeEventNote } from "../writer.js";
import { enrichEvent } from "../enricher.js";
import { loadPeopleFromVault, loadProjectsFromVault } from "../people-loader.js";
import { notify } from "../notify.js";
import type { OnlimeEvent } from "../types.js";
import { writeFile, mkdir } from "node:fs/promises";

const PLAUD_CONFIG = join(homedir(), ".config", "obsidian-sync", "plaud_config.json");
const MEETING_DIR = "/Users/aiparty/Desktop/Obsidian_sinc/1. INPUT/Meeting";

interface PlaudRecording {
  id: string;
  filename: string;
  start_time: number;
  end_time: number;
  duration: number;
  is_trans: number;
  is_summary: number;
}

async function getPlaudAuth(): Promise<{ token: string; apiDomain: string } | null> {
  try {
    const raw = await readFile(PLAUD_CONFIG, "utf-8");
    const cfg = JSON.parse(raw);
    return { token: cfg.token, apiDomain: cfg.api_domain || "https://api-apne1.plaud.ai" };
  } catch {
    console.error("[plaud] No config at", PLAUD_CONFIG);
    return null;
  }
}

async function plaudFetch(url: string, token: string): Promise<any> {
  const res = await fetch(url, {
    headers: {
      "Authorization": `bearer ${token}`,
      "Content-Type": "application/json",
      "Origin": "https://web.plaud.ai",
    },
  });
  if (!res.ok) throw new Error(`Plaud API ${res.status}: ${res.statusText}`);
  return res.json();
}

async function downloadContent(url: string): Promise<string> {
  const res = await fetch(url);
  const buf = await res.arrayBuffer();
  // gzip 해제 시도
  try {
    const { gunzipSync } = await import("node:zlib");
    return gunzipSync(Buffer.from(buf)).toString("utf-8");
  } catch {
    return new TextDecoder().decode(buf);
  }
}

async function getTranscript(fileId: string, auth: { token: string; apiDomain: string }): Promise<string> {
  const detail = await plaudFetch(`${auth.apiDomain}/file/detail/${fileId}`, auth.token);
  const contentList = detail?.data?.content_list || [];

  // 트랜스크립트
  const transItem = contentList.find((c: any) => c.data_type === "transaction" && c.task_status === 1);
  if (!transItem?.data_link) return "";

  const raw = await downloadContent(transItem.data_link);
  try {
    const segments = JSON.parse(raw);
    if (!Array.isArray(segments)) return raw;

    let currentSpeaker = "";
    const lines: string[] = [];
    for (const seg of segments) {
      const speaker = seg.speaker || seg.original_speaker || "화자";
      const content = seg.content || "";
      if (speaker !== currentSpeaker) {
        currentSpeaker = speaker;
        lines.push(`\n**${speaker}**`);
      }
      lines.push(`> ${content}`);
    }
    return lines.join("\n");
  } catch {
    return raw;
  }
}

async function getSummary(fileId: string, auth: { token: string; apiDomain: string }): Promise<string> {
  const detail = await plaudFetch(`${auth.apiDomain}/file/detail/${fileId}`, auth.token);
  const contentList = detail?.data?.content_list || [];

  const sumItem = contentList.find((c: any) => c.data_type === "auto_sum_note" && c.task_status === 1);
  if (!sumItem?.data_link) return "";

  const raw = await downloadContent(sumItem.data_link);
  try {
    const data = JSON.parse(raw);
    return data.ai_content || raw;
  } catch {
    return raw.replace(/!\[PLAUD NOTE\][^\n]*/g, "").trim();
  }
}

async function main() {
  console.log("╔═══════════════════════════════════════╗");
  console.log("║  Plaud → Obsidian 동기화              ║");
  console.log("╚═══════════════════════════════════════╝\n");

  getDb();
  await loadPeopleFromVault();
  await loadProjectsFromVault();

  const auth = await getPlaudAuth();
  if (!auth) return;

  // 오늘 녹음 가져오기
  const data = await plaudFetch(`${auth.apiDomain}/file/simple/web?page=1&pageSize=20`, auth.token);
  const allRecordings: PlaudRecording[] = data.data_file_list || [];

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const todayRecordings = allRecordings.filter((r) => {
    if (!r.start_time) return false;
    const d = new Date(r.start_time);
    return d.toISOString().startsWith(todayStr);
  });

  console.log(`오늘(${todayStr}) 녹음: ${todayRecordings.length}개\n`);

  let created = 0;

  for (const rec of todayRecordings) {
    const sourceId = `plaud_${rec.id}`;

    // 이미 존재하는지 확인 (DB 또는 파일명)
    if (eventExists("plaud", sourceId)) {
      console.log(`⏭️ 이미 존재: ${rec.filename}`);
      continue;
    }

    const startTime = new Date(rec.start_time);
    const duration = Math.round(rec.duration / 60000);
    console.log(`📥 ${rec.filename} (${duration}분)...`);

    // 요약 + 트랜스크립트 가져오기
    let summary = "";
    let transcript = "";

    if (rec.is_summary) {
      console.log("  📝 요약 다운로드...");
      summary = await getSummary(rec.id, auth);
    }

    if (rec.is_trans) {
      console.log("  🎙️ 트랜스크립트 다운로드...");
      transcript = await getTranscript(rec.id, auth);
    }

    // 본문 구성
    const bodyParts = [
      `# ${rec.filename}`,
      "",
      `- 일시: ${startTime.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}`,
      `- 길이: ${duration}분`,
      "",
    ];

    if (summary) {
      bodyParts.push("## AI 요약", "", summary, "");
    }

    if (transcript) {
      bodyParts.push("## 녹취록", "", transcript, "");
    }

    // 참여자 추출 (트랜스크립트에서)
    const speakers = new Set<string>();
    const speakerMatch = transcript.matchAll(/\*\*([^*]+)\*\*/g);
    for (const m of speakerMatch) {
      const name = m[1].trim();
      if (name && name !== "화자" && !name.match(/^Speaker/i)) {
        speakers.add(name);
      }
    }

    let event: OnlimeEvent = {
      id: uuid(),
      timestamp: startTime.toISOString(),
      participants: [...speakers],
      type: "meeting",
      title: rec.filename,
      body: bodyParts.join("\n"),
      source: "plaud",
      source_id: sourceId,
      status: "raw",
      tags: ["meeting", "plaud"],
      related: [],
    };

    event = enrichEvent(event);

    // Meeting 폴더에 기존 형식으로 저장
    const datePrefix = startTime.toISOString().split("T")[0].replace(/-/g, "");
    const safeName = rec.filename.replace(/[/\\:*?"<>|]/g, "").slice(0, 60);
    const filePath = join(MEETING_DIR, `${datePrefix}_${safeName}_Meeting.md`);

    // frontmatter + body
    const frontmatter = [
      "---",
      `created: ${startTime.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }).replace(/\. /g, "-").replace(/\./g, "")}`,
      `date: "[[${todayStr}]]"`,
      `type: meeting`,
      `source: plaud`,
      `plaud_id: ${rec.id}`,
      `participants:`,
      ...event.participants.map((p) => `  - "${p}"`),
      event.project ? `project: "${event.project}"` : "",
      `---`,
    ].filter(Boolean).join("\n");

    const fullContent = frontmatter + "\n\n" + event.body;

    await mkdir(MEETING_DIR, { recursive: true });
    await writeFile(filePath, fullContent, "utf-8");

    event.obsidian_path = filePath;
    insertEvent(event);
    created++;

    console.log(`  ✅ → ${filePath.split("/").pop()}`);
    if (event.project) console.log(`  📁 프로젝트: ${event.project}`);
    console.log();
  }

  if (created > 0) {
    await notify("Onlime Plaud", `${created}개 미팅 노트 생성`);
  }

  console.log(`\n=== 완료: ${created}개 새 노트 생성 ===`);
}

main().catch((err) => {
  console.error("[plaud] Error:", err);
  process.exit(1);
});
