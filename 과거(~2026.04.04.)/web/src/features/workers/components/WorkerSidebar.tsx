"use client";

import { useState, useCallback } from "react";
import { useAppState, useAppDispatch, type Worker, type WorkerStatus } from "../state/store";
import { WorkerAvatar } from "./WorkerAvatar";
import { triggerSync } from "@/lib/api";

type FilterMode = "all" | "running" | "errors";

function matchesFilter(worker: Worker, filter: FilterMode): boolean {
  if (filter === "all") return true;
  if (filter === "running") return worker.status === "running" || worker.status === "syncing";
  if (filter === "errors") return worker.status === "error";
  return true;
}

function statusLabel(status: WorkerStatus): string {
  const labels: Record<WorkerStatus, string> = {
    idle: "Idle",
    running: "Running",
    error: "Error",
    syncing: "Syncing",
  };
  return labels[status];
}

function timeAgo(iso: string | null): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function WorkerSidebar() {
  const { workers, selectedWorkerId } = useAppState();
  const dispatch = useAppDispatch();
  const [filter, setFilter] = useState<FilterMode>("all");

  const filteredWorkers = workers.filter((w) => matchesFilter(w, filter));

  const handleSelect = useCallback(
    (id: string) => {
      dispatch({ type: "SELECT_WORKER", workerId: id === selectedWorkerId ? null : id });
    },
    [dispatch, selectedWorkerId],
  );

  const handleSyncAll = useCallback(async () => {
    try {
      await triggerSync();
    } catch {
      // handled by WS events
    }
  }, []);

  return (
    <aside
      className="flex flex-col border-r shrink-0 overflow-hidden"
      style={{
        width: "var(--sidebar-width)",
        background: "var(--bg-secondary)",
        borderColor: "var(--border-dim)",
      }}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b" style={{ borderColor: "var(--border-dim)" }}>
        <div className="flex items-center justify-between mb-3">
          <h2
            className="cyber-text text-sm"
            style={{ color: "var(--text-secondary)" }}
          >
            WORKERS
          </h2>
          <button
            onClick={handleSyncAll}
            className="mono-text text-xs px-2.5 py-1 rounded transition-colors"
            style={{
              background: "var(--bg-tertiary)",
              color: "var(--accent-cyan)",
              border: "1px solid var(--border-accent)",
            }}
          >
            SYNC ALL
          </button>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1">
          {(["all", "running", "errors"] as FilterMode[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className="mono-text text-xs px-2 py-1 rounded transition-colors capitalize"
              style={{
                background: filter === f ? "var(--bg-tertiary)" : "transparent",
                color: filter === f ? "var(--text-primary)" : "var(--text-muted)",
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Worker List */}
      <div className="flex-1 overflow-y-auto py-2">
        {filteredWorkers.map((worker) => (
          <button
            key={worker.id}
            onClick={() => handleSelect(worker.id)}
            className="w-full flex items-center gap-3 px-4 py-3 transition-all duration-200 text-left"
            style={{
              background:
                selectedWorkerId === worker.id ? "var(--bg-hover)" : "transparent",
              borderLeft:
                selectedWorkerId === worker.id
                  ? "2px solid var(--accent-cyan)"
                  : "2px solid transparent",
            }}
          >
            <WorkerAvatar icon={worker.icon} status={worker.status} size="md" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <span
                  className="text-sm font-medium truncate"
                  style={{ color: "var(--text-primary)" }}
                >
                  {worker.name}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  className="mono-text text-xs"
                  style={{
                    color:
                      worker.status === "error"
                        ? "var(--status-error)"
                        : worker.status === "running" || worker.status === "syncing"
                          ? "var(--status-running)"
                          : "var(--text-muted)",
                  }}
                >
                  {statusLabel(worker.status)}
                </span>
                <span className="mono-text text-xs" style={{ color: "var(--text-muted)" }}>
                  {timeAgo(worker.lastSync)}
                </span>
              </div>
              {worker.errorMessage && (
                <p
                  className="mono-text text-xs mt-1 truncate"
                  style={{ color: "var(--status-error)" }}
                >
                  {worker.errorMessage}
                </p>
              )}
            </div>
          </button>
        ))}
      </div>

      {/* Footer stats */}
      <div
        className="px-4 py-2 border-t mono-text text-xs"
        style={{
          borderColor: "var(--border-dim)",
          color: "var(--text-muted)",
        }}
      >
        {workers.filter((w) => w.status === "running" || w.status === "syncing").length} active /{" "}
        {workers.length} total
      </div>
    </aside>
  );
}
