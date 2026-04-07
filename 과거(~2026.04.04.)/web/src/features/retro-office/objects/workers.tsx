"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import { WORKER_POSITIONS, WORKER_COLORS, STATUS_COLORS } from "../core/constants";
import type { WorkerStatus } from "@/features/workers/state/store";

interface WorkerModelProps {
  id: string;
  name: string;
  icon: string;
  status: WorkerStatus;
  isSelected: boolean;
  onClick: () => void;
}

function WorkerModel({ id, name, icon, status, isSelected, onClick }: WorkerModelProps) {
  const groupRef = useRef<THREE.Group>(null);
  const bodyRef = useRef<THREE.Mesh>(null);
  const leftArmRef = useRef<THREE.Mesh>(null);
  const rightArmRef = useRef<THREE.Mesh>(null);

  const pos = useMemo(
    () => WORKER_POSITIONS.find((w) => w.id === id),
    [id],
  );

  const color = WORKER_COLORS[id] || "#888";
  const statusColor = STATUS_COLORS[status] || STATUS_COLORS.idle;

  // Animation
  useFrame(({ clock }) => {
    if (!groupRef.current) return;
    const t = clock.getElapsedTime();

    // Idle: gentle bobbing
    if (status === "idle") {
      groupRef.current.position.y = Math.sin(t * 1.5) * 0.03;
    }

    // Working: typing animation
    if (status === "running" || status === "syncing") {
      groupRef.current.position.y = 0;
      if (leftArmRef.current) {
        leftArmRef.current.rotation.x = Math.sin(t * 8) * 0.3;
      }
      if (rightArmRef.current) {
        rightArmRef.current.rotation.x = Math.sin(t * 8 + Math.PI) * 0.3;
      }
    }

    // Error: shaking
    if (status === "error") {
      groupRef.current.position.x = Math.sin(t * 15) * 0.02;
    }

    // Selection highlight pulse
    if (bodyRef.current && isSelected) {
      const mat = bodyRef.current.material as THREE.MeshStandardMaterial;
      mat.emissiveIntensity = 0.3 + Math.sin(t * 3) * 0.15;
    }
  });

  if (!pos) return null;

  return (
    <group
      ref={groupRef}
      position={pos.position}
      rotation={[0, pos.rotation, 0]}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
    >
      {/* Body */}
      <mesh ref={bodyRef} position={[0, 0.8, 0]} castShadow>
        <boxGeometry args={[0.5, 0.6, 0.3]} />
        <meshStandardMaterial
          color={color}
          emissive={isSelected ? color : "#000"}
          emissiveIntensity={isSelected ? 0.3 : 0}
          roughness={0.6}
        />
      </mesh>

      {/* Head */}
      <mesh position={[0, 1.3, 0]} castShadow>
        <sphereGeometry args={[0.2, 16, 12]} />
        <meshStandardMaterial color={color} roughness={0.5} />
      </mesh>

      {/* Left Arm */}
      <mesh ref={leftArmRef} position={[-0.35, 0.7, 0]} castShadow>
        <boxGeometry args={[0.12, 0.5, 0.12]} />
        <meshStandardMaterial color={color} roughness={0.7} />
      </mesh>

      {/* Right Arm */}
      <mesh ref={rightArmRef} position={[0.35, 0.7, 0]} castShadow>
        <boxGeometry args={[0.12, 0.5, 0.12]} />
        <meshStandardMaterial color={color} roughness={0.7} />
      </mesh>

      {/* Legs */}
      <mesh position={[-0.12, 0.25, 0]} castShadow>
        <boxGeometry args={[0.14, 0.5, 0.14]} />
        <meshStandardMaterial color="#222" roughness={0.9} />
      </mesh>
      <mesh position={[0.12, 0.25, 0]} castShadow>
        <boxGeometry args={[0.14, 0.5, 0.14]} />
        <meshStandardMaterial color="#222" roughness={0.9} />
      </mesh>

      {/* Status ring at feet */}
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.35, 0.42, 32]} />
        <meshStandardMaterial
          color={statusColor}
          emissive={statusColor}
          emissiveIntensity={0.6}
          transparent
          opacity={0.7}
        />
      </mesh>

      {/* Label */}
      <Html position={[0, 1.7, 0]} center distanceFactor={10}>
        <div
          className="pointer-events-none select-none whitespace-nowrap px-2 py-0.5 rounded text-[10px] font-mono"
          style={{
            background: "rgba(0,0,0,0.75)",
            color: statusColor,
            border: `1px solid ${statusColor}40`,
          }}
        >
          {icon} {name}
        </div>
      </Html>

      {/* Selection indicator */}
      {isSelected && (
        <mesh position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.5, 0.55, 32]} />
          <meshStandardMaterial
            color="#00e5ff"
            emissive="#00e5ff"
            emissiveIntensity={1}
            transparent
            opacity={0.5}
          />
        </mesh>
      )}
    </group>
  );
}

interface WorkerGroupProps {
  workers: Array<{
    id: string;
    name: string;
    icon: string;
    status: WorkerStatus;
  }>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function WorkerGroup({ workers, selectedId, onSelect }: WorkerGroupProps) {
  return (
    <group>
      {workers.map((w) => (
        <WorkerModel
          key={w.id}
          id={w.id}
          name={w.name}
          icon={w.icon}
          status={w.status}
          isSelected={selectedId === w.id}
          onClick={() => onSelect(w.id)}
        />
      ))}
    </group>
  );
}
