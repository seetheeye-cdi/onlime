import { writeFile, rename, access, mkdir, readFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";
import matter from "gray-matter";
import type { OnlimeEvent } from "./types.js";

const VAULT_PATH = "/Users/aiparty/Desktop/Obsidian_sinc";
const INPUT_PATH = join(VAULT_PATH, "1. INPUT");

function getMonthFolder(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function dateStr(iso: string): string {
  const d = new Date(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}${m}${day}`;
}

function timeStr(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}00`;
}

function sanitizeFilename(name: string): string {
  return name
    .replace(/[/\\:*?"<>|]/g, "")
    .replace(/\s+/g, "")
    .slice(0, 50);
}

export function buildFilename(event: OnlimeEvent): string {
  const date = dateStr(event.timestamp);
  const time = timeStr(event.timestamp);
  const keyword = sanitizeFilename(event.title || event.source_id.slice(0, 20));
  return `${date}_${time}_${keyword}_${event.source}.md`;
}

export function buildFilePath(event: OnlimeEvent): string {
  const monthFolder = getMonthFolder();
  return join(INPUT_PATH, monthFolder, buildFilename(event));
}

export function eventToMarkdown(event: OnlimeEvent): string {
  const frontmatter: Record<string, unknown> = {
    date: event.timestamp.split("T")[0],
    participants: event.participants,
    type: event.type,
    source: event.source,
    source_id: event.source_id,
    created: event.timestamp,
    status: event.status,
  };

  if (event.project) frontmatter.project = event.project;
  if (event.title) frontmatter.title = event.title;
  if (event.tags.length > 0) frontmatter.tags = event.tags;
  if (event.summary) frontmatter.summary = event.summary;

  const body = event.body;
  return matter.stringify(body, frontmatter);
}

export async function writeEventNote(event: OnlimeEvent): Promise<string> {
  const filePath = buildFilePath(event);
  const dir = dirname(filePath);

  // 디렉토리 생성
  await mkdir(dir, { recursive: true });

  const content = eventToMarkdown(event);

  // Atomic write: tmp → rename
  const tmpPath = join(tmpdir(), `onlime-${randomBytes(8).toString("hex")}.md`);
  await writeFile(tmpPath, content, "utf-8");
  await rename(tmpPath, filePath);

  return filePath;
}

export async function fileExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

// 데일리 노트 경로
export function getDailyNotePath(dateIso?: string): string {
  const d = dateIso ? new Date(dateIso) : new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return join(VAULT_PATH, "2. OUTPUT", "Daily", `${y}-${m}-${day}.md`);
}

// 데일리 노트의 특정 섹션에 텍스트 삽입 (markdown surgery 최소화)
export async function appendToDailySection(
  section: string,
  content: string,
  dateIso?: string
): Promise<void> {
  const filePath = getDailyNotePath(dateIso);

  let existing: string;
  try {
    existing = await readFile(filePath, "utf-8");
  } catch {
    // 데일리 노트가 없으면 생성하지 않음 (Templater가 생성)
    console.log(`[writer] Daily note not found: ${filePath}`);
    return;
  }

  const sectionHeader = `## ${section}`;
  const idx = existing.indexOf(sectionHeader);
  if (idx === -1) {
    // 섹션이 없으면 파일 끝에 추가
    const updated = existing + `\n${sectionHeader}\n${content}\n`;
    const tmpPath = join(tmpdir(), `onlime-daily-${randomBytes(8).toString("hex")}.md`);
    await writeFile(tmpPath, updated, "utf-8");
    await rename(tmpPath, filePath);
    return;
  }

  // 섹션 헤더 바로 다음 줄에 삽입
  const afterHeader = idx + sectionHeader.length;
  const nextNewline = existing.indexOf("\n", afterHeader);
  const insertPos = nextNewline !== -1 ? nextNewline + 1 : existing.length;

  const updated =
    existing.slice(0, insertPos) + content + "\n" + existing.slice(insertPos);

  const tmpPath = join(tmpdir(), `onlime-daily-${randomBytes(8).toString("hex")}.md`);
  await writeFile(tmpPath, updated, "utf-8");
  await rename(tmpPath, filePath);
}
