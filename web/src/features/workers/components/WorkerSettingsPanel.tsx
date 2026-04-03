"use client";

import { useCallback } from "react";
import { useSelectedWorker, useAppDispatch } from "../state/store";
import { WorkerAvatar } from "./WorkerAvatar";
import { triggerSync } from "@/lib/api";

export function WorkerSettingsPanel() {
  const worker = useSelectedWorker();
  const dispatch = useAppDispatch();

  const handleSync = useCallback(async () => {
    if (!worker) return;
    dispatch({
      type: "SET_WORKER_STATUS",
      workerId: worker.id,
      status: "syncing",
    });
    try {
      await triggerSync([worker.id]);
    } catch (err) {
      dispatch({
        type: "SET_WORKER_STATUS",
        workerId: worker.id,
        status: "error",
        errorMessage: err instanceof Error ? err.message : "Sync failed",
      });
    }
  }, [worker, dispatch]);

  if (!worker) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <span className="text-4xl">👈</span>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Worker를 선택하세요
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="flex items-center gap-4 px-5 py-4 border-b shrink-0"
        style={{ borderColor: "var(--border-dim)" }}
      >
        <WorkerAvatar icon={worker.icon} status={worker.status} size="lg" />
        <div>
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            {worker.name}
          </h2>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {worker.description}
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-6">
        {/* Status section */}
        <section>
          <h3
            className="cyber-text text-xs mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            STATUS
          </h3>
          <div
            className="rounded-lg p-4 space-y-3"
            style={{ background: "var(--bg-tertiary)" }}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                상태
              </span>
              <div className="flex items-center gap-2">
                <span className={`status-dot status-dot--${worker.status}`} />
                <span className="mono-text text-sm capitalize" style={{ color: "var(--text-primary)" }}>
                  {worker.status}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                마지막 동기화
              </span>
              <span className="mono-text text-sm" style={{ color: "var(--text-primary)" }}>
                {worker.lastSync
                  ? new Date(worker.lastSync).toLocaleString("ko-KR")
                  : "N/A"}
              </span>
            </div>
            {worker.errorMessage && (
              <div
                className="rounded p-2 text-sm"
                style={{ background: "rgba(255,51,85,0.1)", color: "var(--status-error)" }}
              >
                {worker.errorMessage}
              </div>
            )}
          </div>
        </section>

        {/* Config section */}
        <section>
          <h3
            className="cyber-text text-xs mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            CONFIGURATION
          </h3>
          <div
            className="rounded-lg p-4 space-y-3"
            style={{ background: "var(--bg-tertiary)" }}
          >
            {Object.entries(worker.config).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between">
                <span className="mono-text text-sm" style={{ color: "var(--text-secondary)" }}>
                  {key}
                </span>
                <span className="mono-text text-sm" style={{ color: "var(--text-primary)" }}>
                  {String(value)}
                </span>
              </div>
            ))}
            {Object.keys(worker.config).length === 0 && (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                설정 항목 없음
              </p>
            )}
          </div>
        </section>

        {/* Actions */}
        <section>
          <h3
            className="cyber-text text-xs mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            ACTIONS
          </h3>
          <div className="flex flex-col gap-2">
            <button
              onClick={handleSync}
              disabled={worker.status === "syncing" || worker.status === "running"}
              className="w-full py-2.5 rounded-lg text-sm font-medium transition-all duration-200 disabled:opacity-40"
              style={{
                background: "var(--accent-cyan)",
                color: "var(--bg-primary)",
              }}
            >
              {worker.status === "syncing" ? "동기화 중..." : "동기화 실행"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
