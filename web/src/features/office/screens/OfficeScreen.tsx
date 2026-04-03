"use client";

import { useEffect, useCallback } from "react";
import {
  StoreProvider,
  useAppState,
  useAppDispatch,
} from "@/features/workers/state/store";
import { HeaderBar } from "@/features/workers/components/HeaderBar";
import { WorkerSidebar } from "@/features/workers/components/WorkerSidebar";
import { WorkerChatPanel } from "@/features/workers/components/WorkerChatPanel";
import { WorkerSettingsPanel } from "@/features/workers/components/WorkerSettingsPanel";
import { HQSidebar } from "@/features/office/components/HQSidebar";
import { RetroOffice3D } from "@/features/retro-office/RetroOffice3D";
import { getWebSocket } from "@/lib/websocket";
import { fetchWorkers, fetchRecentNotes } from "@/lib/api";

function ViewSwitch() {
  const { view, selectedWorkerId } = useAppState();

  // Show chat if AI worker is selected
  if (selectedWorkerId === "ai") {
    return <WorkerChatPanel />;
  }

  // Show settings if a non-AI worker is selected
  if (selectedWorkerId && view !== "office3d") {
    return <WorkerSettingsPanel />;
  }

  // Show 3D office or settings based on view
  if (view === "office3d" || !selectedWorkerId) {
    return <RetroOffice3D />;
  }

  if (view === "settings") {
    return <WorkerSettingsPanel />;
  }

  return <RetroOffice3D />;
}

function ViewTabs() {
  const { view, selectedWorkerId } = useAppState();
  const dispatch = useAppDispatch();

  if (!selectedWorkerId || selectedWorkerId === "ai") return null;

  return (
    <div
      className="flex border-b shrink-0"
      style={{ borderColor: "var(--border-dim)", background: "var(--bg-secondary)" }}
    >
      {(
        [
          { id: "office3d", label: "3D OFFICE", icon: "🏢" },
          { id: "settings", label: "SETTINGS", icon: "⚙️" },
        ] as const
      ).map((tab) => (
        <button
          key={tab.id}
          onClick={() => dispatch({ type: "SET_VIEW", view: tab.id })}
          className="flex items-center gap-1.5 px-4 py-2 transition-all duration-200"
          style={{
            borderBottom:
              view === tab.id
                ? "2px solid var(--accent-cyan)"
                : "2px solid transparent",
            color: view === tab.id ? "var(--accent-cyan)" : "var(--text-muted)",
          }}
        >
          <span className="text-xs">{tab.icon}</span>
          <span className="cyber-text text-[10px]">{tab.label}</span>
        </button>
      ))}
    </div>
  );
}

function OfficeLayout() {
  const dispatch = useAppDispatch();

  // Initialize data and WebSocket
  const loadData = useCallback(async () => {
    try {
      const [workers, notes] = await Promise.allSettled([
        fetchWorkers(),
        fetchRecentNotes(),
      ]);

      if (workers.status === "fulfilled") {
        dispatch({
          type: "SET_WORKERS",
          workers: workers.value.map((w) => ({
            id: w.id,
            name: w.name,
            status: (w.status as "idle" | "running" | "error" | "syncing") || "idle",
            lastSync: w.last_sync,
            errorMessage: w.error_message,
            description: "",
            icon:
              w.id === "gcal"
                ? "📅"
                : w.id === "plaud"
                  ? "🎙️"
                  : w.id === "daily"
                    ? "📝"
                    : "🤖",
            config: {},
          })),
        });
      }

      if (notes.status === "fulfilled") {
        dispatch({
          type: "SET_RECENT_NOTES",
          notes: notes.value.map((n) => ({
            path: n.path,
            title: n.title,
            modified: n.modified,
            type: n.type as "meeting" | "daily" | "standalone" | "inbox",
          })),
        });
      }
    } catch {
      // API not available, use default state
    }
  }, [dispatch]);

  useEffect(() => {
    loadData();

    // Connect WebSocket
    const ws = getWebSocket();
    ws.connect((connected) => {
      dispatch({ type: "SET_WS_CONNECTED", connected });
    });

    ws.on("worker_status", (data) => {
      dispatch({
        type: "SET_WORKER_STATUS",
        workerId: data.worker_id as string,
        status: data.status as "idle" | "running" | "error" | "syncing",
        errorMessage: data.error_message as string | undefined,
      });
    });

    ws.on("sync_event", (data) => {
      dispatch({
        type: "ADD_SYNC_EVENT",
        event: {
          id: `${Date.now()}`,
          workerId: data.worker_id as string,
          action: data.action as string,
          detail: data.detail as string,
          timestamp: data.timestamp as string,
        },
      });
    });

    ws.on("sync_complete", (data) => {
      dispatch({
        type: "SET_WORKER_LAST_SYNC",
        workerId: data.worker_id as string,
        lastSync: data.timestamp as string,
      });
      dispatch({
        type: "SET_WORKER_STATUS",
        workerId: data.worker_id as string,
        status: "idle",
      });
      // Reload notes after sync
      loadData();
    });

    return () => ws.disconnect();
  }, [dispatch, loadData]);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <HeaderBar />
      <div className="flex flex-1 overflow-hidden">
        <WorkerSidebar />
        <main className="flex flex-col flex-1 overflow-hidden">
          <ViewTabs />
          <div className="flex-1 overflow-hidden" style={{ background: "var(--bg-primary)" }}>
            <ViewSwitch />
          </div>
        </main>
        <HQSidebar />
      </div>
    </div>
  );
}

export function OfficeScreen() {
  return (
    <StoreProvider>
      <OfficeLayout />
    </StoreProvider>
  );
}
