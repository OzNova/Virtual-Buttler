"use client";

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";

// Quiet orb: matte light-gray sphere that breathes with `level` (0..1).
// No neon — scale + roughness shift only, Apple-quiet.
export default function Orb({ level = 0.2 }: { level?: number }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const target = 1 + Math.min(1, Math.max(0, level)) * 0.18 + Math.sin(t * 1.6) * 0.015;
    if (ref.current) {
      ref.current.scale.setScalar(target);
      ref.current.rotation.y = t * 0.12;
    }
  });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[1, 48, 48]} />
      <meshStandardMaterial color="#e8e8ed" roughness={0.55} metalness={0.05} />
    </mesh>
  );
}
