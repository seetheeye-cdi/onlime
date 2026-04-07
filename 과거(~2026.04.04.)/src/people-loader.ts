import { readdir, readFile } from "node:fs/promises";
import { join, basename } from "node:path";
import { v4 as uuid } from "uuid";
import matter from "gray-matter";
import { upsertPerson, upsertProject } from "./db.js";
import type { PersonRecord, ProjectRecord } from "./types.js";

const VAULT_PATH = "/Users/aiparty/Desktop/Obsidian_sinc";

/**
 * Obsidian 볼트의 People 노트를 스캔하여 SQLite people 테이블에 로드
 */
export async function loadPeopleFromVault(): Promise<number> {
  let count = 0;

  // 1. 1. INPUT/People/ 폴더
  const peoplePath = join(VAULT_PATH, "1. INPUT", "People");
  count += await scanPeopleDir(peoplePath);

  // 2. 볼트 루트의 🙍‍♂️ 프리픽스 파일들
  count += await scanRootPeople(VAULT_PATH);

  console.log(`[people-loader] Loaded ${count} people from vault`);
  return count;
}

async function scanPeopleDir(dirPath: string): Promise<number> {
  let count = 0;
  try {
    const files = await readdir(dirPath);
    for (const file of files) {
      if (!file.endsWith(".md")) continue;
      const person = await parsePeopleNote(join(dirPath, file));
      if (person) {
        upsertPerson(person);
        count++;
      }
    }
  } catch {
    console.log(`[people-loader] Directory not found: ${dirPath}`);
  }
  return count;
}

async function scanRootPeople(vaultPath: string): Promise<number> {
  let count = 0;
  try {
    const files = await readdir(vaultPath);
    for (const file of files) {
      if (!file.endsWith(".md")) continue;
      // 🙍‍♂️ 또는 👤 프리픽스 매칭
      if (!file.startsWith("🙍") && !file.startsWith("👤")) continue;
      const person = await parsePeopleNote(join(vaultPath, file));
      if (person) {
        upsertPerson(person);
        count++;
      }
    }
  } catch (err) {
    console.error("[people-loader] Error scanning root:", err);
  }
  return count;
}

async function parsePeopleNote(filePath: string): Promise<PersonRecord | null> {
  try {
    const raw = await readFile(filePath, "utf-8");
    const { data } = matter(raw);

    const filename = basename(filePath, ".md");

    // 이름 추출: 이모지 프리픽스 제거
    const name = filename
      .replace(/^[🙍‍♂️👤]+/u, "")
      .replace(/^[\u200d\u2640\u2642\ufe0f]+/u, "")
      .trim();

    if (!name) return null;

    // 위키링크 = 파일명 그대로
    const wikilink = `[[${filename}]]`;

    // aliases 추출
    const aliases: string[] = [];
    if (data.aliases) {
      if (Array.isArray(data.aliases)) {
        aliases.push(...data.aliases.filter((a: unknown) => typeof a === "string"));
      } else if (typeof data.aliases === "string") {
        aliases.push(data.aliases);
      }
    }
    // 이름 자체도 alias에 추가
    if (!aliases.includes(name)) aliases.push(name);

    // "_" 앞의 짧은 이름도 alias에 추가 (예: "유민승_테크노크라츠 대표" → "유민승")
    if (name.includes("_")) {
      const shortName = name.split("_")[0].trim();
      if (shortName && !aliases.includes(shortName)) {
        aliases.push(shortName);
      }
    }
    // 공백 앞의 성+이름도 alias에 추가 (예: "김현석 경기도의원" → "김현석")
    if (name.includes(" ") && !name.includes("_")) {
      const parts = name.split(" ");
      // 한국어 이름 패턴: 2-3글자 성+이름
      if (parts[0].length >= 2 && parts[0].length <= 4) {
        if (!aliases.includes(parts[0])) aliases.push(parts[0]);
      }
    }

    // 이메일
    const emails: string[] = [];
    if (data.email) {
      const email = String(data.email).trim();
      if (email && email !== "d" && email.includes("@")) {
        emails.push(email);
      }
    }

    // 조직
    const organization = data.organization || data.company || undefined;

    // 프로젝트
    const projects: string[] = [];
    if (data.project) {
      if (Array.isArray(data.project)) {
        projects.push(...data.project.map(String));
      } else {
        projects.push(String(data.project));
      }
    }

    return {
      id: uuid(),
      name,
      wikilink,
      aliases,
      emails,
      kakao_name: undefined, // 수동 설정 필요
      slack_id: undefined,
      organization: organization ? String(organization) : undefined,
      projects,
      last_contact: undefined,
      interaction_count: 0,
    };
  } catch (err) {
    console.error(`[people-loader] Error parsing ${filePath}:`, err);
    return null;
  }
}

/**
 * Obsidian 볼트의 Project 노트를 스캔하여 SQLite projects 테이블에 로드
 */
export async function loadProjectsFromVault(): Promise<number> {
  const projectsPath = join(VAULT_PATH, "2. OUTPUT", "Projects");
  let count = 0;

  try {
    const files = await readdir(projectsPath);
    for (const file of files) {
      if (!file.endsWith(".md")) continue;
      const project = await parseProjectNote(join(projectsPath, file));
      if (project) {
        upsertProject(project);
        count++;
      }
    }
  } catch {
    console.log("[people-loader] Projects directory not found, creating default projects");
    // 기본 프로젝트 시드
    const defaults: Array<{ name: string; keywords: string[] }> = [
      { name: "에이아이당", keywords: ["에이아이당", "AIPARTY", "AI당", "정당", "창당"] },
      { name: "더해커톤", keywords: ["더해커톤", "THEHACKATHON", "해커톤"] },
      { name: "테크노크라츠", keywords: ["테크노크라츠", "Technocrats", "테크노"] },
      { name: "참치상사", keywords: ["참치상사", "참치"] },
      { name: "국회의원실", keywords: ["의원실", "김소희", "국회", "공보"] },
    ];
    for (const d of defaults) {
      upsertProject({
        id: uuid(),
        name: d.name,
        wikilink: `[[${d.name}]]`,
        keywords: d.keywords,
        active: true,
      });
      count++;
    }
  }

  console.log(`[people-loader] Loaded ${count} projects`);
  return count;
}

async function parseProjectNote(filePath: string): Promise<ProjectRecord | null> {
  try {
    const raw = await readFile(filePath, "utf-8");
    const { data } = matter(raw);

    const name = basename(filePath, ".md");
    const wikilink = `[[${name}]]`;
    const keywords: string[] = data.keywords || data.aliases || [name];
    const active = data.status !== "archived" && data.status !== "completed";

    return {
      id: uuid(),
      name,
      wikilink,
      keywords: keywords.map(String),
      active,
    };
  } catch {
    return null;
  }
}

// 직접 실행 가능
if (
  process.argv[1]?.endsWith("people-loader.ts") ||
  process.argv[1]?.endsWith("people-loader.js")
) {
  const people = await loadPeopleFromVault();
  const projects = await loadProjectsFromVault();
  console.log(`Done: ${people} people, ${projects} projects`);
}
