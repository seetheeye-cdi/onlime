"use client";

import {
  createContext,
  useContext,
  useReducer,
  type ReactNode,
  type Dispatch,
} from "react";

// ===== Types =====

export type WorkerStatus = "idle" | "running" | "error" | "syncing";

export interface Worker {
  id: string;
  name: string;
  description: string;
  icon: string; // emoji
  status: WorkerStatus;
  lastSync: string | null;
  errorMessage: string | null;
  config: Record<string, unknown>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  thinking?: string;
}

export interface NoteItem {
  path: string;
  title: string;
  modified: string;
  type: "meeting" | "daily" | "standalone" | "inbox";
}

export interface SyncEvent {
  id: string;
  workerId: string;
  action: string;
  timestamp: string;
  detail: string;
}

export interface AppState {
  workers: Worker[];
  selectedWorkerId: string | null;
  chatMessages: ChatMessage[];
  chatInput: string;
  isChatLoading: boolean;
  showThinking: boolean;
  recentNotes: NoteItem[];
  syncHistory: SyncEvent[];
  theme: "dark" | "light";
  view: "chat" | "settings" | "office3d";
  hqTab: "inbox" | "history" | "analytics";
  wsConnected: boolean;
}

// ===== Default Workers =====

const DEFAULT_WORKERS: Worker[] = [
  {
    id: "gcal",
    name: "GCal Worker",
    description: "Google Calendar 동기화 및 미팅 노트 생성",
    icon: "📅",
    status: "idle",
    lastSync: null,
    errorMessage: null,
    config: { syncDaysBack: 7, syncDaysForward: 14 },
  },
  {
    id: "plaud",
    name: "Plaud Worker",
    description: "Plaud.ai 녹음 수집 및 트랜스크립트 연동",
    icon: "🎙️",
    status: "idle",
    lastSync: null,
    errorMessage: null,
    config: { limit: 50, days: 7 },
  },
  {
    id: "daily",
    name: "Daily Note Worker",
    description: "데일리 노트 스케줄 및 요약 삽입",
    icon: "📝",
    status: "idle",
    lastSync: null,
    errorMessage: null,
    config: {},
  },
  {
    id: "ai",
    name: "AI Assistant",
    description: "Claude 기반 AI 어시스턴트",
    icon: "🤖",
    status: "idle",
    lastSync: null,
    errorMessage: null,
    config: { model: "claude-sonnet-4-6" },
  },
];

// ===== Actions =====

type Action =
  | { type: "SELECT_WORKER"; workerId: string | null }
  | { type: "SET_WORKER_STATUS"; workerId: string; status: WorkerStatus; errorMessage?: string }
  | { type: "SET_WORKER_LAST_SYNC"; workerId: string; lastSync: string }
  | { type: "SET_VIEW"; view: AppState["view"] }
  | { type: "SET_HQ_TAB"; tab: AppState["hqTab"] }
  | { type: "SET_THEME"; theme: AppState["theme"] }
  | { type: "ADD_CHAT_MESSAGE"; message: ChatMessage }
  | { type: "SET_CHAT_INPUT"; input: string }
  | { type: "SET_CHAT_LOADING"; loading: boolean }
  | { type: "TOGGLE_THINKING" }
  | { type: "SET_RECENT_NOTES"; notes: NoteItem[] }
  | { type: "ADD_SYNC_EVENT"; event: SyncEvent }
  | { type: "SET_SYNC_HISTORY"; events: SyncEvent[] }
  | { type: "SET_WS_CONNECTED"; connected: boolean }
  | { type: "SET_WORKERS"; workers: Worker[] };

// ===== Reducer =====

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "SELECT_WORKER":
      return {
        ...state,
        selectedWorkerId: action.workerId,
        view: action.workerId === "ai" ? "chat" : state.view === "chat" ? "settings" : state.view,
      };
    case "SET_WORKER_STATUS":
      return {
        ...state,
        workers: state.workers.map((w) =>
          w.id === action.workerId
            ? { ...w, status: action.status, errorMessage: action.errorMessage ?? null }
            : w
        ),
      };
    case "SET_WORKER_LAST_SYNC":
      return {
        ...state,
        workers: state.workers.map((w) =>
          w.id === action.workerId ? { ...w, lastSync: action.lastSync } : w
        ),
      };
    case "SET_VIEW":
      return { ...state, view: action.view };
    case "SET_HQ_TAB":
      return { ...state, hqTab: action.tab };
    case "SET_THEME": {
      if (typeof document !== "undefined") {
        document.documentElement.setAttribute("data-theme", action.theme);
      }
      return { ...state, theme: action.theme };
    }
    case "ADD_CHAT_MESSAGE":
      return { ...state, chatMessages: [...state.chatMessages, action.message] };
    case "SET_CHAT_INPUT":
      return { ...state, chatInput: action.input };
    case "SET_CHAT_LOADING":
      return { ...state, isChatLoading: action.loading };
    case "TOGGLE_THINKING":
      return { ...state, showThinking: !state.showThinking };
    case "SET_RECENT_NOTES":
      return { ...state, recentNotes: action.notes };
    case "ADD_SYNC_EVENT":
      return { ...state, syncHistory: [action.event, ...state.syncHistory].slice(0, 100) };
    case "SET_SYNC_HISTORY":
      return { ...state, syncHistory: action.events };
    case "SET_WS_CONNECTED":
      return { ...state, wsConnected: action.connected };
    case "SET_WORKERS":
      return { ...state, workers: action.workers };
    default:
      return state;
  }
}

// ===== Initial State =====

const initialState: AppState = {
  workers: DEFAULT_WORKERS,
  selectedWorkerId: null,
  chatMessages: [],
  chatInput: "",
  isChatLoading: false,
  showThinking: false,
  recentNotes: [],
  syncHistory: [],
  theme: "dark",
  view: "office3d",
  hqTab: "inbox",
  wsConnected: false,
};

// ===== Context =====

const StateContext = createContext<AppState>(initialState);
const DispatchContext = createContext<Dispatch<Action>>(() => {});

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  return (
    <StateContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>{children}</DispatchContext.Provider>
    </StateContext.Provider>
  );
}

export function useAppState() {
  return useContext(StateContext);
}

export function useAppDispatch() {
  return useContext(DispatchContext);
}

export function useSelectedWorker(): Worker | null {
  const state = useAppState();
  return state.workers.find((w) => w.id === state.selectedWorkerId) ?? null;
}
