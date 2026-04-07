/**
 * Onlime v3 — Rebuild SQLite Index from .md files
 *
 * .md 파일이 소스 오브 트루스. SQLite는 재구축 가능한 인덱스.
 * 이 스크립트는 SQLite를 완전히 비우고 볼트의 .md 파일에서 재구축합니다.
 *
 * Usage: npx tsx src/rebuild-index.ts
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { join, basename } from "node:path";
import { v4 as uuid } from "uuid";
import matter from "gray-matter";
import { getDb, clearRebuildableTables, insertEvent, upsertPerson, upsertProject } from "./db.js";
import type { OnlimeEvent, PersonRecord, ProjectRecord } from "./types.js";

const VAULT_PATH = "/Users/aiparty/Desktop/Obsidian_sinc";
const INPUT_PATH = join(VAULT_PATH, "1. INPUT");

async function scanDir(dirPath: string): Promise<string[]> {
  const results: string[] = [];
  try {
    const entries = await readdir(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = join(dirPath, entry.name);
      if (entry.isDirectory()) {
        // Archive 폴더는 스킵
        if (entry.name === "Archive" || entry.name.startsWith(".")) continue;
        results.push(...(await scanDir(fullPath)));
      } else if (entry.name.endsWith(".md")) {
        results.push(fullPath);
      }
    }
  } catch {
    // 디렉토리가 없으면 무시
  }
  return results;
}

async function main() {
  console.log("[rebuild] Starting index rebuild...");
  console.log(`[rebuild] Vault: ${VAULT_PATH}`);

  // DB 초기화
  getDb();

  // 재구축 가능한 테이블 비우기
  clearRebuildableTables();
  console.log("[rebuild] Cleared events, people, projects tables");

  let eventCount = 0;
  let peopleCount = 0;
  let projectCount = 0;

  // 1. INPUT 폴더의 이벤트 노트 스캔
  console.log("[rebuild] Scanning 1. INPUT/ for events...");
  const inputFiles = await scanDir(INPUT_PATH);

  for (const filePath of inputFiles) {
    try {
      const raw = await readFile(filePath, "utf-8");
      const { data } = matter(raw);

      // 이벤트 노트 (source + source_id 필수)
      if (data.source && data.source_id) {
        const event: OnlimeEvent = {
          id: uuid(),
          timestamp: data.created || data.date || new Date().toISOString(),
          participants: (data.participants as string[]) || [],
          project: data.project as string | undefined,
          type: data.type || "note",
          title: data.title || basename(filePath, ".md"),
          body: "",
          source: data.source,
          source_id: data.source_id,
          status: data.status || "raw",
          tags: (data.tags as string[]) || [],
          related: [],
          obsidian_path: filePath,
        };

        if (insertEvent(event)) eventCount++;
      }

      // People 노트
      if (
        data.type === "person" ||
        data.type === "people" ||
        (Array.isArray(data.type) && data.type.includes("people"))
      ) {
        const name = basename(filePath, ".md")
          .replace(/^[🙍‍♂️👤]+/u, "")
          .replace(/^[\u200d\u2640\u2642\ufe0f]+/u, "")
          .trim();

        if (name) {
          const person: PersonRecord = {
            id: uuid(),
            name,
            wikilink: `[[${basename(filePath, ".md")}]]`,
            aliases: Array.isArray(data.aliases) ? data.aliases : data.aliases ? [data.aliases] : [name],
            emails: data.email && String(data.email).includes("@") ? [String(data.email)] : [],
            kakao_name: undefined,
            slack_id: undefined,
            organization: data.organization || data.company || undefined,
            projects: Array.isArray(data.project) ? data.project : data.project ? [data.project] : [],
            last_contact: undefined,
            interaction_count: 0,
          };

          upsertPerson(person);
          peopleCount++;
        }
      }
    } catch (err) {
      console.error(`[rebuild] Error processing ${filePath}:`, err);
    }
  }

  // 2. 루트 레벨 People 노트
  console.log("[rebuild] Scanning root for people notes...");
  try {
    const rootFiles = await readdir(VAULT_PATH);
    for (const file of rootFiles) {
      if (!file.endsWith(".md")) continue;
      if (!file.startsWith("🙍") && !file.startsWith("👤")) continue;

      const filePath = join(VAULT_PATH, file);
      const raw = await readFile(filePath, "utf-8");
      const { data } = matter(raw);

      const name = file
        .replace(/\.md$/, "")
        .replace(/^[🙍‍♂️👤]+/u, "")
        .replace(/^[\u200d\u2640\u2642\ufe0f]+/u, "")
        .trim();

      if (name) {
        const person: PersonRecord = {
          id: uuid(),
          name,
          wikilink: `[[${file.replace(/\.md$/, "")}]]`,
          aliases: Array.isArray(data.aliases) ? data.aliases : data.aliases ? [data.aliases] : [name],
          emails: data.email && String(data.email).includes("@") ? [String(data.email)] : [],
          kakao_name: undefined,
          slack_id: undefined,
          organization: data.organization || data.company || undefined,
          projects: [],
          last_contact: undefined,
          interaction_count: 0,
        };

        upsertPerson(person);
        peopleCount++;
      }
    }
  } catch {
    // ignore
  }

  // 3. Projects 폴더 스캔
  console.log("[rebuild] Scanning projects...");
  const projectsPath = join(VAULT_PATH, "2. OUTPUT", "Projects");
  try {
    const projectFiles = await readdir(projectsPath);
    for (const file of projectFiles) {
      if (!file.endsWith(".md")) continue;
      const filePath = join(projectsPath, file);
      const raw = await readFile(filePath, "utf-8");
      const { data } = matter(raw);

      const name = file.replace(/\.md$/, "");
      const project: ProjectRecord = {
        id: uuid(),
        name,
        wikilink: `[[${name}]]`,
        keywords: (data.keywords as string[]) || (data.aliases as string[]) || [name],
        active: data.status !== "archived" && data.status !== "completed",
      };

      upsertProject(project);
      projectCount++;
    }
  } catch {
    console.log("[rebuild] No projects directory found");
  }

  console.log(`[rebuild] Done! Rebuilt: ${eventCount} events, ${peopleCount} people, ${projectCount} projects`);
}

main().catch((err) => {
  console.error("[rebuild] Fatal error:", err);
  process.exit(1);
});
