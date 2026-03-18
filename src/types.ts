// === Onlime v3 Type System ===
// 3축: 시간(timestamp) / 사람(participants) / 일(project)

export type Source = "kakao" | "gmail" | "gcal" | "slack" | "plaud" | "manual";
export type EventType = "chat" | "email" | "calendar" | "meeting" | "action" | "note";
export type EventStatus = "raw" | "enriched" | "reviewed";

export interface OnlimeEvent {
  id: string;

  // 3축
  timestamp: string; // ISO 8601
  participants: string[]; // [[위키링크]] 배열
  project?: string; // [[프로젝트명]]

  // 콘텐츠
  type: EventType;
  title?: string;
  body: string;
  summary?: string;

  // 메타데이터 (디테일)
  source: Source;
  source_id: string;
  status: EventStatus;
  tags: string[];

  // 연결
  related: string[];
  obsidian_path?: string;
}

// 카카오톡 (kmsg CLI 출력 형식)
export interface KakaoMessage {
  author: string;
  time_raw: string;
  body: string;
}

export interface KakaoChat {
  chat: string;
  fetched_at: string;
  count: number;
  messages: KakaoMessage[];
}

// 사람 매칭
export interface PersonRecord {
  id: string;
  name: string;
  wikilink: string; // [[🙍‍♂️이름]]
  aliases: string[]; // 정확 일치용
  emails: string[];
  kakao_name?: string;
  slack_id?: string;
  organization?: string;
  projects: string[];
  last_contact?: string;
  interaction_count: number;
}

// 프로젝트 매칭
export interface ProjectRecord {
  id: string;
  name: string;
  wikilink: string; // [[프로젝트명]]
  keywords: string[]; // 자동 매칭용 키워드
  active: boolean;
}

// 설정
export interface OnlimeConfig {
  obsidianVaultPath: string;
  inputPath: string; // 1. INPUT 경로
  pollIntervals: {
    kakao: number; // minutes
    gmail: number;
    gcal: number;
    slack: number;
  };
  excludeChats: string[];
  watchChats: string[];
  summarizeHour: number;
  morningBriefHour: number;
}

// 헬스 체크
export interface HealthCheck {
  source: Source;
  status: "ok" | "warning" | "error";
  message: string;
  events_count: number;
  checked_at: string;
}
