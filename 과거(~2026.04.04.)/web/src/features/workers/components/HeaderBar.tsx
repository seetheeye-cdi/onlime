"use client";

import { useAppState, useAppDispatch } from "../state/store";

export function HeaderBar() {
  const { theme, wsConnected } = useAppState();
  const dispatch = useAppDispatch();

  return (
    <header
      className="flex items-center justify-between px-5 border-b shrink-0"
      style={{
        height: "var(--header-height)",
        background: "var(--bg-secondary)",
        borderColor: "var(--border-dim)",
      }}
    >
      {/* Left: Logo */}
      <div className="flex items-center gap-3">
        <h1
          className="cyber-text text-2xl tracking-wider"
          style={{ color: "var(--accent-cyan)" }}
        >
          ONLIME STUDIO
        </h1>
        <span
          className="mono-text px-2 py-0.5 rounded text-xs"
          style={{
            background: "var(--bg-tertiary)",
            color: "var(--text-muted)",
          }}
        >
          v0.1.0
        </span>
      </div>

      {/* Right: Status + Theme Toggle */}
      <div className="flex items-center gap-4">
        {/* Connection Status */}
        <div className="flex items-center gap-2">
          <span
            className={`status-dot ${wsConnected ? "status-dot--running" : "status-dot--error"}`}
          />
          <span className="mono-text text-xs" style={{ color: "var(--text-muted)" }}>
            {wsConnected ? "CONNECTED" : "OFFLINE"}
          </span>
        </div>

        {/* Theme Toggle */}
        <button
          onClick={() =>
            dispatch({
              type: "SET_THEME",
              theme: theme === "dark" ? "light" : "dark",
            })
          }
          className="flex items-center justify-center w-8 h-8 rounded-md transition-colors"
          style={{ background: "var(--bg-tertiary)" }}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          <span className="text-sm">{theme === "dark" ? "☀️" : "🌙"}</span>
        </button>
      </div>
    </header>
  );
}
