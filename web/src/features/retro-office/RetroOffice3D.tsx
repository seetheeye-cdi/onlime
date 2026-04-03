"use client";

import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Environment } from "./scene/environment";
import { FurnitureGroup } from "./objects/furniture";
import { WorkerGroup } from "./objects/workers";
import { FURNITURE } from "./core/constants";
import { useAppState, useAppDispatch } from "@/features/workers/state/store";

function Scene() {
  const { workers, selectedWorkerId } = useAppState();
  const dispatch = useAppDispatch();

  return (
    <>
      <Environment />
      <FurnitureGroup items={FURNITURE} />
      <WorkerGroup
        workers={workers}
        selectedId={selectedWorkerId}
        onSelect={(id) => dispatch({ type: "SELECT_WORKER", workerId: id })}
      />
      <OrbitControls
        target={[0, 1, 0]}
        maxPolarAngle={Math.PI / 2.2}
        minDistance={5}
        maxDistance={25}
        enablePan={false}
      />
    </>
  );
}

function LoadingFallback() {
  return (
    <div
      className="flex items-center justify-center h-full"
      style={{ background: "var(--bg-primary)" }}
    >
      <div className="flex flex-col items-center gap-3">
        <div
          className="w-8 h-8 border-2 rounded-full animate-spin"
          style={{
            borderColor: "var(--border-dim)",
            borderTopColor: "var(--accent-cyan)",
          }}
        />
        <span className="mono-text text-xs" style={{ color: "var(--text-muted)" }}>
          Loading 3D Office...
        </span>
      </div>
    </div>
  );
}

export function RetroOffice3D() {
  return (
    <div className="w-full h-full relative">
      <Suspense fallback={<LoadingFallback />}>
        <Canvas
          shadows
          camera={{
            position: [12, 10, 12],
            fov: 45,
            near: 0.1,
            far: 100,
          }}
          style={{ background: "#0a0a0f" }}
        >
          <Scene />
        </Canvas>
      </Suspense>

      {/* Overlay corner label */}
      <div
        className="absolute top-3 left-3 mono-text text-[10px] px-2 py-1 rounded"
        style={{
          background: "rgba(0,0,0,0.6)",
          color: "var(--text-muted)",
          border: "1px solid var(--border-dim)",
        }}
      >
        3D OFFICE VIEW
      </div>
    </div>
  );
}
