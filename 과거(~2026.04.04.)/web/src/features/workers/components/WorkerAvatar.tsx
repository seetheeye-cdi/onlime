"use client";

import type { WorkerStatus } from "../state/store";

interface WorkerAvatarProps {
  icon: string;
  status: WorkerStatus;
  size?: "sm" | "md" | "lg";
  onClick?: () => void;
}

const SIZE_MAP = {
  sm: { container: 32, icon: 16 },
  md: { container: 40, icon: 20 },
  lg: { container: 56, icon: 28 },
};

const STATUS_BORDER: Record<WorkerStatus, string> = {
  idle: "var(--status-idle)",
  running: "var(--status-running)",
  error: "var(--status-error)",
  syncing: "var(--status-syncing)",
};

const STATUS_GLOW: Record<WorkerStatus, string> = {
  idle: "none",
  running: "var(--glow-green)",
  error: "var(--glow-red)",
  syncing: "var(--glow-cyan)",
};

export function WorkerAvatar({ icon, status, size = "md", onClick }: WorkerAvatarProps) {
  const { container, icon: iconSize } = SIZE_MAP[size];

  return (
    <button
      onClick={onClick}
      className="relative flex items-center justify-center rounded-lg shrink-0 transition-all duration-200"
      style={{
        width: container,
        height: container,
        background: "var(--bg-tertiary)",
        border: `2px solid ${STATUS_BORDER[status]}`,
        boxShadow: STATUS_GLOW[status],
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <span style={{ fontSize: iconSize }}>{icon}</span>
      {/* Status indicator dot */}
      <span
        className={`absolute -bottom-0.5 -right-0.5 status-dot status-dot--${status}`}
        style={{ width: 10, height: 10, border: "2px solid var(--bg-panel)" }}
      />
    </button>
  );
}
