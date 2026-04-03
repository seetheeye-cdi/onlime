"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { FLOOR_SIZE, WALL_HEIGHT } from "../core/constants";

function Floor() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow position={[0, 0, 0]}>
      <planeGeometry args={[FLOOR_SIZE * 2, FLOOR_SIZE * 2]} />
      <meshStandardMaterial color="#1a1a2e" roughness={0.8} metalness={0.2} />
    </mesh>
  );
}

function GridLines() {
  return (
    <gridHelper
      args={[FLOOR_SIZE * 2, FLOOR_SIZE * 2, "#2a2a4e", "#1e1e3a"]}
      position={[0, 0.01, 0]}
    />
  );
}

function Walls() {
  const wallMaterial = (
    <meshStandardMaterial color="#12121a" roughness={0.9} transparent opacity={0.6} />
  );

  return (
    <group>
      {/* Back wall */}
      <mesh position={[0, WALL_HEIGHT / 2, -FLOOR_SIZE]} receiveShadow>
        <boxGeometry args={[FLOOR_SIZE * 2, WALL_HEIGHT, 0.2]} />
        {wallMaterial}
      </mesh>
      {/* Left wall */}
      <mesh position={[-FLOOR_SIZE, WALL_HEIGHT / 2, 0]} receiveShadow>
        <boxGeometry args={[0.2, WALL_HEIGHT, FLOOR_SIZE * 2]} />
        {wallMaterial}
      </mesh>
      {/* Right wall */}
      <mesh position={[FLOOR_SIZE, WALL_HEIGHT / 2, 0]} receiveShadow>
        <boxGeometry args={[0.2, WALL_HEIGHT, FLOOR_SIZE * 2]} />
        {wallMaterial}
      </mesh>
    </group>
  );
}

function Lighting() {
  const lightRef = useRef<THREE.DirectionalLight>(null);

  // Subtle day/night cycle
  useFrame(({ clock }) => {
    if (!lightRef.current) return;
    const t = Math.sin(clock.getElapsedTime() * 0.05) * 0.5 + 0.5;
    lightRef.current.intensity = 0.5 + t * 0.5;
    lightRef.current.color.setHSL(0.12, 0.1, 0.5 + t * 0.3);
  });

  return (
    <>
      <ambientLight intensity={0.3} color="#4466aa" />
      <directionalLight
        ref={lightRef}
        position={[10, 12, 8]}
        intensity={0.8}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-far={50}
        shadow-camera-left={-15}
        shadow-camera-right={15}
        shadow-camera-top={15}
        shadow-camera-bottom={-15}
      />
      {/* Accent lights */}
      <pointLight position={[0, 3, 0]} intensity={0.4} color="#00e5ff" distance={15} />
      <pointLight position={[-6, 2, -6]} intensity={0.2} color="#4285f4" distance={10} />
      <pointLight position={[6, 2, -6]} intensity={0.2} color="#ff6b35" distance={10} />
      <pointLight position={[-6, 2, 6]} intensity={0.2} color="#39ff14" distance={10} />
      <pointLight position={[6, 2, 6]} intensity={0.2} color="#b24dff" distance={10} />
    </>
  );
}

export function Environment() {
  return (
    <group>
      <Floor />
      <GridLines />
      <Walls />
      <Lighting />
      <fog attach="fog" args={["#0a0a0f", 15, 40]} />
    </group>
  );
}
