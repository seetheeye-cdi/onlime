import type { WorkerPosition, FurnitureItem } from "./types";

export const FLOOR_SIZE = 20;
export const WALL_HEIGHT = 4;

export const WORKER_POSITIONS: WorkerPosition[] = [
  { id: "gcal", position: [-4, 0, -2], rotation: 0, deskPosition: [-4, 0.5, -3] },
  { id: "plaud", position: [4, 0, -2], rotation: Math.PI, deskPosition: [4, 0.5, -3] },
  { id: "daily", position: [-4, 0, 4], rotation: 0, deskPosition: [-4, 0.5, 3] },
  { id: "ai", position: [4, 0, 4], rotation: Math.PI, deskPosition: [4, 0.5, 3] },
];

export const FURNITURE: FurnitureItem[] = [
  // Desks for each worker
  { id: "desk-gcal", type: "desk", position: [-4, 0, -3] },
  { id: "desk-plaud", type: "desk", position: [4, 0, -3] },
  { id: "desk-daily", type: "desk", position: [-4, 0, 3] },
  { id: "desk-ai", type: "desk", position: [4, 0, 3] },
  // Chairs
  { id: "chair-gcal", type: "chair", position: [-4, 0, -1.5] },
  { id: "chair-plaud", type: "chair", position: [4, 0, -1.5] },
  { id: "chair-daily", type: "chair", position: [-4, 0, 4.5] },
  { id: "chair-ai", type: "chair", position: [4, 0, 4.5] },
  // Server rack (center back)
  { id: "server-1", type: "server", position: [0, 0, -7] },
  // Plants
  { id: "plant-1", type: "plant", position: [-8, 0, -7] },
  { id: "plant-2", type: "plant", position: [8, 0, -7] },
  { id: "plant-3", type: "plant", position: [-8, 0, 7] },
  { id: "plant-4", type: "plant", position: [8, 0, 7] },
  // Shelves
  { id: "shelf-1", type: "shelf", position: [0, 0, 7], rotation: 0 },
];

export const WORKER_COLORS: Record<string, string> = {
  gcal: "#4285f4",  // Google blue
  plaud: "#ff6b35",  // Orange
  daily: "#39ff14",  // Neon green
  ai: "#b24dff",     // Purple
};

export const STATUS_COLORS = {
  idle: "#5a5a78",
  running: "#39ff14",
  error: "#ff3355",
  syncing: "#00e5ff",
} as const;
