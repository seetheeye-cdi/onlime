"use client";

import { useAppState, useAppDispatch, type AppState } from "@/features/workers/state/store";

type HQTab = AppState["hqTab"];

const TABS: { id: HQTab; label: string; icon: string }[] = [
  { id: "inbox", label: "INBOX", icon: "📥" },
  { id: "history", label: "HISTORY", icon: "📜" },
  { id: "analytics", label: "STATS", icon: "📊" },
];

function InboxPanel() {
  const { recentNotes } = useAppState();

  return (
    <div className="flex-1 overflow-y-auto">
      {recentNotes.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-2">
          <span className="text-2xl">📭</span>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            최근 노트 없음
          </p>
        </div>
      ) : (
        <div className="space-y-1 p-2">
          {recentNotes.map((note) => (
            <div
              key={note.path}
              className="rounded-md px-3 py-2 transition-colors cursor-pointer"
              style={{ background: "var(--bg-tertiary)" }}
            >
              <div className="flex items-center gap-2">
                <span className="text-xs">
                  {note.type === "meeting" ? "📅" : note.type === "daily" ? "📝" : "📄"}
                </span>
                <span
                  className="text-sm truncate flex-1"
                  style={{ color: "var(--text-primary)" }}
                >
                  {note.title}
                </span>
              </div>
              <span
                className="mono-text text-[10px] mt-0.5 block"
                style={{ color: "var(--text-muted)" }}
              >
                {new Date(note.modified).toLocaleString("ko-KR", {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryPanel() {
  const { syncHistory } = useAppState();

  return (
    <div className="flex-1 overflow-y-auto">
      {syncHistory.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-2">
          <span className="text-2xl">📜</span>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            동기화 이력 없음
          </p>
        </div>
      ) : (
        <div className="space-y-1 p-2">
          {syncHistory.map((event) => (
            <div
              key={event.id}
              className="rounded-md px-3 py-2"
              style={{ background: "var(--bg-tertiary)" }}
            >
              <div className="flex items-center gap-2">
                <span className={`status-dot status-dot--running`} />
                <span className="mono-text text-xs" style={{ color: "var(--text-primary)" }}>
                  {event.action}
                </span>
              </div>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                {event.detail}
              </p>
              <span
                className="mono-text text-[10px] mt-0.5 block"
                style={{ color: "var(--text-muted)" }}
              >
                {new Date(event.timestamp).toLocaleTimeString("ko-KR")}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AnalyticsPanel() {
  const { workers, syncHistory, recentNotes } = useAppState();
  const activeWorkers = workers.filter(
    (w) => w.status === "running" || w.status === "syncing",
  ).length;
  const errorWorkers = workers.filter((w) => w.status === "error").length;

  const stats = [
    { label: "Active Workers", value: activeWorkers, color: "var(--status-running)" },
    { label: "Errors", value: errorWorkers, color: "var(--status-error)" },
    { label: "Recent Syncs", value: syncHistory.length, color: "var(--accent-cyan)" },
    { label: "Notes Created", value: recentNotes.length, color: "var(--accent-purple)" },
  ];

  return (
    <div className="p-3 space-y-3">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="rounded-lg p-3"
          style={{ background: "var(--bg-tertiary)" }}
        >
          <span className="mono-text text-xs block" style={{ color: "var(--text-muted)" }}>
            {stat.label}
          </span>
          <span
            className="cyber-text text-2xl block mt-1"
            style={{ color: stat.color }}
          >
            {stat.value}
          </span>
        </div>
      ))}

      {/* Worker status bars */}
      <div className="mt-4">
        <h4 className="mono-text text-xs mb-2" style={{ color: "var(--text-muted)" }}>
          WORKER HEALTH
        </h4>
        {workers.map((w) => (
          <div key={w.id} className="flex items-center gap-2 py-1.5">
            <span className="text-sm">{w.icon}</span>
            <span className="mono-text text-xs flex-1" style={{ color: "var(--text-secondary)" }}>
              {w.name}
            </span>
            <span className={`status-dot status-dot--${w.status}`} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function HQSidebar() {
  const { hqTab } = useAppState();
  const dispatch = useAppDispatch();

  return (
    <aside
      className="flex flex-col border-l shrink-0 overflow-hidden"
      style={{
        width: "var(--hq-width)",
        background: "var(--bg-secondary)",
        borderColor: "var(--border-dim)",
      }}
    >
      {/* Tab bar */}
      <div
        className="flex border-b shrink-0"
        style={{ borderColor: "var(--border-dim)" }}
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => dispatch({ type: "SET_HQ_TAB", tab: tab.id })}
            className="flex-1 flex items-center justify-center gap-1.5 py-2.5 transition-all duration-200"
            style={{
              borderBottom:
                hqTab === tab.id
                  ? "2px solid var(--accent-cyan)"
                  : "2px solid transparent",
              color: hqTab === tab.id ? "var(--accent-cyan)" : "var(--text-muted)",
            }}
          >
            <span className="text-xs">{tab.icon}</span>
            <span className="cyber-text text-[10px]">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {hqTab === "inbox" && <InboxPanel />}
      {hqTab === "history" && <HistoryPanel />}
      {hqTab === "analytics" && <AnalyticsPanel />}
    </aside>
  );
}
