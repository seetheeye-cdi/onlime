const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, text);
  }
  return res.json();
}

// ===== Worker endpoints =====

export interface WorkerStatusResponse {
  id: string;
  name: string;
  status: string;
  last_sync: string | null;
  error_message: string | null;
  is_available: boolean;
}

export function fetchWorkers() {
  return request<WorkerStatusResponse[]>("/api/workers");
}

export function fetchWorkerStatus(id: string) {
  return request<WorkerStatusResponse>(`/api/workers/${id}/status`);
}

// ===== Sync =====

export interface SyncResult {
  success: boolean;
  message: string;
  events: Array<{ action: string; detail: string; timestamp: string }>;
}

export function triggerSync(connectors?: string[]) {
  return request<SyncResult>("/api/sync/run", {
    method: "POST",
    body: JSON.stringify({ connectors }),
  });
}

// ===== Notes =====

export interface NoteResponse {
  path: string;
  title: string;
  modified: string;
  type: string;
}

export function fetchRecentNotes(limit = 20) {
  return request<NoteResponse[]>(`/api/notes/recent?limit=${limit}`);
}

// ===== Calendar =====

export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  location: string | null;
  attendees: string[];
}

export function fetchCalendarEvents(days = 7) {
  return request<CalendarEvent[]>(`/api/calendar/events?days=${days}`);
}

// ===== Recordings =====

export interface Recording {
  id: string;
  title: string;
  duration_minutes: number;
  created_at: string;
  has_transcript: boolean;
}

export function fetchRecentRecordings(limit = 20) {
  return request<Recording[]>(`/api/recordings/recent?limit=${limit}`);
}

// ===== Chat =====

export interface ChatRequest {
  message: string;
  context?: string;
}

export interface ChatResponse {
  reply: string;
  thinking?: string;
}

export function sendChatMessage(data: ChatRequest) {
  return request<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
