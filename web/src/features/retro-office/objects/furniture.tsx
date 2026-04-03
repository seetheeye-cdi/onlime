"use client";

import type { FurnitureItem } from "../core/types";

function Desk({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      {/* Desktop surface */}
      <mesh position={[0, 0.75, 0]} castShadow receiveShadow>
        <boxGeometry args={[2, 0.08, 1]} />
        <meshStandardMaterial color="#2a2a3e" roughness={0.6} metalness={0.3} />
      </mesh>
      {/* Legs */}
      {[
        [-0.9, 0.375, -0.4],
        [0.9, 0.375, -0.4],
        [-0.9, 0.375, 0.4],
        [0.9, 0.375, 0.4],
      ].map((pos, i) => (
        <mesh key={i} position={pos as [number, number, number]} castShadow>
          <boxGeometry args={[0.06, 0.75, 0.06]} />
          <meshStandardMaterial color="#1a1a2e" metalness={0.5} />
        </mesh>
      ))}
      {/* Monitor */}
      <mesh position={[0, 1.2, -0.3]} castShadow>
        <boxGeometry args={[0.8, 0.5, 0.04]} />
        <meshStandardMaterial color="#0a0a12" roughness={0.3} metalness={0.6} />
      </mesh>
      {/* Monitor screen glow */}
      <mesh position={[0, 1.2, -0.28]}>
        <planeGeometry args={[0.7, 0.4]} />
        <meshStandardMaterial
          color="#00e5ff"
          emissive="#00e5ff"
          emissiveIntensity={0.3}
          transparent
          opacity={0.6}
        />
      </mesh>
      {/* Monitor stand */}
      <mesh position={[0, 0.95, -0.3]} castShadow>
        <boxGeometry args={[0.08, 0.35, 0.08]} />
        <meshStandardMaterial color="#1a1a2e" metalness={0.5} />
      </mesh>
    </group>
  );
}

function Chair({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      {/* Seat */}
      <mesh position={[0, 0.45, 0]} castShadow>
        <boxGeometry args={[0.5, 0.06, 0.5]} />
        <meshStandardMaterial color="#2a1a3e" roughness={0.8} />
      </mesh>
      {/* Backrest */}
      <mesh position={[0, 0.75, -0.22]} castShadow>
        <boxGeometry args={[0.5, 0.55, 0.06]} />
        <meshStandardMaterial color="#2a1a3e" roughness={0.8} />
      </mesh>
      {/* Pole */}
      <mesh position={[0, 0.22, 0]}>
        <cylinderGeometry args={[0.03, 0.03, 0.44]} />
        <meshStandardMaterial color="#333" metalness={0.8} />
      </mesh>
      {/* Base */}
      <mesh position={[0, 0.02, 0]}>
        <cylinderGeometry args={[0.25, 0.25, 0.04]} />
        <meshStandardMaterial color="#333" metalness={0.8} />
      </mesh>
    </group>
  );
}

function ServerRack({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      {/* Main body */}
      <mesh position={[0, 1.2, 0]} castShadow>
        <boxGeometry args={[1.2, 2.4, 0.6]} />
        <meshStandardMaterial color="#1a1a2e" roughness={0.7} metalness={0.4} />
      </mesh>
      {/* Rack units (blinking LEDs) */}
      {Array.from({ length: 6 }).map((_, i) => (
        <group key={i}>
          <mesh position={[-0.3, 0.4 + i * 0.35, 0.31]}>
            <boxGeometry args={[0.04, 0.04, 0.02]} />
            <meshStandardMaterial
              color={i % 2 === 0 ? "#39ff14" : "#00e5ff"}
              emissive={i % 2 === 0 ? "#39ff14" : "#00e5ff"}
              emissiveIntensity={0.8}
            />
          </mesh>
          <mesh position={[-0.15, 0.4 + i * 0.35, 0.31]}>
            <boxGeometry args={[0.04, 0.04, 0.02]} />
            <meshStandardMaterial
              color="#ff6b35"
              emissive="#ff6b35"
              emissiveIntensity={i % 3 === 0 ? 0.8 : 0.2}
            />
          </mesh>
        </group>
      ))}
    </group>
  );
}

function Plant({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      {/* Pot */}
      <mesh position={[0, 0.2, 0]} castShadow>
        <cylinderGeometry args={[0.2, 0.15, 0.4]} />
        <meshStandardMaterial color="#3a2a1e" roughness={0.9} />
      </mesh>
      {/* Leaves */}
      <mesh position={[0, 0.6, 0]} castShadow>
        <sphereGeometry args={[0.3, 8, 6]} />
        <meshStandardMaterial color="#1a5a2a" roughness={0.8} />
      </mesh>
    </group>
  );
}

function Shelf({ position, rotation = 0 }: { position: [number, number, number]; rotation?: number }) {
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      {/* Frame */}
      <mesh position={[0, 0.8, 0]} castShadow>
        <boxGeometry args={[2.5, 1.6, 0.4]} />
        <meshStandardMaterial color="#1e1e2e" roughness={0.8} metalness={0.2} transparent opacity={0.5} />
      </mesh>
      {/* Shelves */}
      {[0.3, 0.8, 1.3].map((y, i) => (
        <mesh key={i} position={[0, y, 0]}>
          <boxGeometry args={[2.4, 0.04, 0.35]} />
          <meshStandardMaterial color="#2a2a3e" roughness={0.7} />
        </mesh>
      ))}
    </group>
  );
}

const COMPONENT_MAP = {
  desk: Desk,
  chair: Chair,
  server: ServerRack,
  plant: Plant,
  shelf: Shelf,
} as const;

export function FurnitureGroup({ items }: { items: FurnitureItem[] }) {
  return (
    <group>
      {items.map((item) => {
        const Component = COMPONENT_MAP[item.type];
        return (
          <Component
            key={item.id}
            position={item.position}
            {...(item.rotation !== undefined ? { rotation: item.rotation } : {})}
          />
        );
      })}
    </group>
  );
}
