import Database from "better-sqlite3";
import { join } from "node:path";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import type { OnlimeEvent, PersonRecord, ProjectRecord, HealthCheck } from "./types.js";

const DB_DIR = join(homedir(), ".onlime");
const DB_PATH = join(DB_DIR, "onlime.db");

let _db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (_db) return _db;

  mkdirSync(DB_DIR, { recursive: true });

  _db = new Database(DB_PATH);
  _db.pragma("journal_mode = WAL");
  _db.pragma("foreign_keys = ON");

  initSchema(_db);
  return _db;
}

function initSchema(db: Database.Database): void {
  db.exec(`
    -- 이벤트 인덱스 (.md 파일에서 재구축 가능)
    CREATE TABLE IF NOT EXISTS events (
      id TEXT PRIMARY KEY,
      source TEXT NOT NULL,
      source_id TEXT NOT NULL,
      type TEXT NOT NULL,
      timestamp TEXT NOT NULL,
      title TEXT,
      participants TEXT,         -- JSON array
      project TEXT,
      status TEXT DEFAULT 'raw',
      obsidian_path TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(source, source_id)
    );

    -- 동기화 커서 (운영 상태, .md에 없음)
    CREATE TABLE IF NOT EXISTS sync_cursors (
      source TEXT PRIMARY KEY,
      cursor_value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    -- 사람 테이블 (People 노트에서 재구축 가능)
    CREATE TABLE IF NOT EXISTS people (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      wikilink TEXT NOT NULL UNIQUE,
      aliases TEXT,              -- JSON array
      emails TEXT,               -- JSON array
      kakao_name TEXT,
      slack_id TEXT,
      organization TEXT,
      projects TEXT,             -- JSON array
      last_contact TEXT,
      interaction_count INTEGER DEFAULT 0
    );

    -- 프로젝트 테이블 (Project 노트에서 재구축 가능)
    CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      wikilink TEXT NOT NULL UNIQUE,
      keywords TEXT,             -- JSON array
      active INTEGER DEFAULT 1
    );

    -- 헬스 체크 (운영 상태)
    CREATE TABLE IF NOT EXISTS health_checks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL,
      status TEXT NOT NULL,
      message TEXT,
      events_count INTEGER DEFAULT 0,
      checked_at TEXT NOT NULL
    );

    -- 피드백/평점 (운영 상태)
    CREATE TABLE IF NOT EXISTS ratings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      target_type TEXT NOT NULL,
      target_date TEXT NOT NULL,
      rating INTEGER,
      comment TEXT,
      created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_events_source ON events(source, timestamp);
    CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_events_project ON events(project);
    CREATE INDEX IF NOT EXISTS idx_health_source ON health_checks(source, checked_at);
  `);
}

// === Sync Cursor ===

export function getCursor(source: string): string | null {
  const db = getDb();
  const row = db
    .prepare("SELECT cursor_value FROM sync_cursors WHERE source = ?")
    .get(source) as { cursor_value: string } | undefined;
  return row?.cursor_value ?? null;
}

export function setCursor(source: string, value: string): void {
  const db = getDb();
  db.prepare(
    `INSERT INTO sync_cursors (source, cursor_value, updated_at)
     VALUES (?, ?, ?)
     ON CONFLICT(source) DO UPDATE SET cursor_value = ?, updated_at = ?`
  ).run(source, value, new Date().toISOString(), value, new Date().toISOString());
}

// === Events ===

export function insertEvent(event: OnlimeEvent): boolean {
  const db = getDb();
  try {
    db.prepare(
      `INSERT INTO events (id, source, source_id, type, timestamp, title, participants, project, status, obsidian_path, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      event.id,
      event.source,
      event.source_id,
      event.type,
      event.timestamp,
      event.title ?? null,
      JSON.stringify(event.participants),
      event.project ?? null,
      event.status,
      event.obsidian_path ?? null,
      new Date().toISOString()
    );
    return true;
  } catch (err: unknown) {
    if (err instanceof Error && err.message.includes("UNIQUE constraint")) {
      return false; // 이미 처리된 이벤트
    }
    throw err;
  }
}

export function eventExists(source: string, sourceId: string): boolean {
  const db = getDb();
  const row = db
    .prepare("SELECT 1 FROM events WHERE source = ? AND source_id = ?")
    .get(source, sourceId);
  return !!row;
}

export function updateEventPath(id: string, obsidianPath: string): void {
  const db = getDb();
  db.prepare("UPDATE events SET obsidian_path = ?, status = 'enriched' WHERE id = ?").run(
    obsidianPath,
    id
  );
}

// === People ===

export function getAllPeople(): PersonRecord[] {
  const db = getDb();
  const rows = db.prepare("SELECT * FROM people").all() as Array<Record<string, unknown>>;
  return rows.map(parsePersonRow);
}

export function findPersonByAlias(alias: string): PersonRecord | null {
  const db = getDb();
  // 정확 일치: name, kakao_name, 또는 aliases JSON 배열 내 일치
  const row = db
    .prepare(
      `SELECT * FROM people
       WHERE name = ? OR kakao_name = ?
       OR EXISTS (SELECT 1 FROM json_each(aliases) WHERE json_each.value = ?)
       OR EXISTS (SELECT 1 FROM json_each(emails) WHERE json_each.value = ?)`
    )
    .get(alias, alias, alias, alias) as Record<string, unknown> | undefined;
  return row ? parsePersonRow(row) : null;
}

export function upsertPerson(person: PersonRecord): void {
  const db = getDb();
  db.prepare(
    `INSERT INTO people (id, name, wikilink, aliases, emails, kakao_name, slack_id, organization, projects, last_contact, interaction_count)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(wikilink) DO UPDATE SET
       name = ?, aliases = ?, emails = ?, kakao_name = ?, slack_id = ?,
       organization = ?, projects = ?, last_contact = ?, interaction_count = ?`
  ).run(
    person.id,
    person.name,
    person.wikilink,
    JSON.stringify(person.aliases),
    JSON.stringify(person.emails),
    person.kakao_name ?? null,
    person.slack_id ?? null,
    person.organization ?? null,
    JSON.stringify(person.projects),
    person.last_contact ?? null,
    person.interaction_count,
    // ON CONFLICT UPDATE values
    person.name,
    JSON.stringify(person.aliases),
    JSON.stringify(person.emails),
    person.kakao_name ?? null,
    person.slack_id ?? null,
    person.organization ?? null,
    JSON.stringify(person.projects),
    person.last_contact ?? null,
    person.interaction_count
  );
}

export function updateLastContact(wikilink: string, date: string): void {
  const db = getDb();
  db.prepare(
    `UPDATE people SET last_contact = ?, interaction_count = interaction_count + 1 WHERE wikilink = ?`
  ).run(date, wikilink);
}

function parsePersonRow(row: Record<string, unknown>): PersonRecord {
  return {
    id: row.id as string,
    name: row.name as string,
    wikilink: row.wikilink as string,
    aliases: JSON.parse((row.aliases as string) || "[]"),
    emails: JSON.parse((row.emails as string) || "[]"),
    kakao_name: row.kakao_name as string | undefined,
    slack_id: row.slack_id as string | undefined,
    organization: row.organization as string | undefined,
    projects: JSON.parse((row.projects as string) || "[]"),
    last_contact: row.last_contact as string | undefined,
    interaction_count: (row.interaction_count as number) || 0,
  };
}

// === Projects ===

export function getAllProjects(): ProjectRecord[] {
  const db = getDb();
  const rows = db.prepare("SELECT * FROM projects WHERE active = 1").all() as Array<
    Record<string, unknown>
  >;
  return rows.map((row) => ({
    id: row.id as string,
    name: row.name as string,
    wikilink: row.wikilink as string,
    keywords: JSON.parse((row.keywords as string) || "[]"),
    active: !!(row.active as number),
  }));
}

export function upsertProject(project: ProjectRecord): void {
  const db = getDb();
  db.prepare(
    `INSERT INTO projects (id, name, wikilink, keywords, active)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(wikilink) DO UPDATE SET
       name = ?, keywords = ?, active = ?`
  ).run(
    project.id,
    project.name,
    project.wikilink,
    JSON.stringify(project.keywords),
    project.active ? 1 : 0,
    project.name,
    JSON.stringify(project.keywords),
    project.active ? 1 : 0
  );
}

export function findProjectByKeyword(text: string): ProjectRecord | null {
  const projects = getAllProjects();
  for (const project of projects) {
    for (const keyword of project.keywords) {
      if (text.includes(keyword)) {
        return project;
      }
    }
  }
  return null;
}

// === Health ===

export function logHealth(check: HealthCheck): void {
  const db = getDb();
  db.prepare(
    `INSERT INTO health_checks (source, status, message, events_count, checked_at)
     VALUES (?, ?, ?, ?, ?)`
  ).run(check.source, check.status, check.message, check.events_count, check.checked_at);

  // 30일 이전 헬스 로그 정리
  db.prepare("DELETE FROM health_checks WHERE checked_at < datetime('now', '-30 days')").run();
}

export function getLastHealth(source: string): HealthCheck | null {
  const db = getDb();
  const row = db
    .prepare("SELECT * FROM health_checks WHERE source = ? ORDER BY checked_at DESC LIMIT 1")
    .get(source) as Record<string, unknown> | undefined;
  if (!row) return null;
  return {
    source: row.source as Source,
    status: row.status as HealthCheck["status"],
    message: row.message as string,
    events_count: row.events_count as number,
    checked_at: row.checked_at as string,
  };
}

// === Rebuild ===

export function clearRebuildableTables(): void {
  const db = getDb();
  db.exec("DELETE FROM events");
  db.exec("DELETE FROM people");
  db.exec("DELETE FROM projects");
}

// Type import for health source
type Source = import("./types.js").Source;
