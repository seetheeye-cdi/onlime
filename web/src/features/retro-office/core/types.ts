export interface WorkerPosition {
  id: string;
  position: [number, number, number];
  rotation: number;
  deskPosition: [number, number, number];
}

export interface FurnitureItem {
  id: string;
  type: "desk" | "chair" | "server" | "plant" | "shelf";
  position: [number, number, number];
  rotation?: number;
  scale?: number;
}
