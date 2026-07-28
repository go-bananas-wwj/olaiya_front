import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// Slow-drifting 4-point sparkles and hearts floating in the sky around the
// bottle. Basic pastel materials (no HDR) so they never fight the bloom of
// the ingredient orbs.

function sparkleGeo() {
  const s = new THREE.Shape()
  s.moveTo(0, 1)
  s.quadraticCurveTo(0.14, 0.14, 1, 0)
  s.quadraticCurveTo(0.14, -0.14, 0, -1)
  s.quadraticCurveTo(-0.14, -0.14, -1, 0)
  s.quadraticCurveTo(-0.14, 0.14, 0, 1)
  return new THREE.ShapeGeometry(s, 8)
}

function heartGeo() {
  const s = new THREE.Shape()
  s.moveTo(0, 0.32)
  s.bezierCurveTo(0, 0.62, -0.45, 0.62, -0.45, 0.32)
  s.bezierCurveTo(-0.45, 0.08, 0, -0.1, 0, -0.38)
  s.bezierCurveTo(0, -0.1, 0.45, 0.08, 0.45, 0.32)
  s.bezierCurveTo(0.45, 0.62, 0, 0.62, 0, 0.32)
  return new THREE.ShapeGeometry(s, 12)
}

const SPECS = [
  { kind: 'sparkle', x: -2.5, y: 2.6, z: -1.6, s: 0.13, c: '#f4b8d2', sp: 0.5, p: 0.0 },
  { kind: 'heart', x: -1.7, y: 1.4, z: -2.0, s: 0.12, c: '#f2a8c4', sp: 0.4, p: 1.2 },
  { kind: 'sparkle', x: -2.9, y: 0.9, z: -1.2, s: 0.09, c: '#c9b8f0', sp: 0.6, p: 2.4 },
  { kind: 'heart', x: -2.2, y: 3.3, z: -2.4, s: 0.09, c: '#e8c8f0', sp: 0.35, p: 3.1 },
  { kind: 'sparkle', x: 1.9, y: 3.1, z: -1.8, s: 0.15, c: '#f9d9a8', sp: 0.45, p: 0.7 },
  { kind: 'heart', x: 2.6, y: 2.0, z: -1.4, s: 0.11, c: '#f4b8d2', sp: 0.55, p: 1.9 },
  { kind: 'sparkle', x: 2.9, y: 0.7, z: -2.2, s: 0.1, c: '#a8d8e8', sp: 0.5, p: 2.8 },
  { kind: 'heart', x: 1.5, y: 0.5, z: -1.0, s: 0.08, c: '#e8c8f0', sp: 0.6, p: 4.0 },
  { kind: 'sparkle', x: -1.2, y: 3.6, z: -2.6, s: 0.08, c: '#a8d8e8', sp: 0.4, p: 5.2 },
  { kind: 'sparkle', x: 3.2, y: 3.4, z: -2.8, s: 0.11, c: '#f4b8d2', sp: 0.35, p: 0.4 },
  { kind: 'heart', x: -3.2, y: 2.0, z: -2.6, s: 0.1, c: '#f9d9a8', sp: 0.45, p: 3.6 },
  { kind: 'sparkle', x: 0.4, y: 3.9, z: -3.0, s: 0.09, c: '#c9b8f0', sp: 0.5, p: 2.0 },
  { kind: 'heart', x: 2.2, y: 1.1, z: 0.9, s: 0.07, c: '#f2a8c4', sp: 0.65, p: 1.5 },
  { kind: 'sparkle', x: -2.0, y: 1.9, z: 0.8, s: 0.06, c: '#f9d9a8', sp: 0.7, p: 4.6 },
]

export default function Particles() {
  const refs = useRef([])
  const geos = useMemo(() => ({ sparkle: sparkleGeo(), heart: heartGeo() }), [])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    SPECS.forEach((s, i) => {
      const m = refs.current[i]
      if (!m) return
      m.position.y = s.y + Math.sin(t * s.sp + s.p) * 0.22
      m.position.x = s.x + Math.sin(t * s.sp * 0.6 + s.p * 2.1) * 0.1
      m.rotation.z = Math.sin(t * s.sp * 0.8 + s.p) * 0.35
    })
  })

  return (
    <group>
      {SPECS.map((s, i) => (
        <mesh
          key={i}
          ref={(el) => (refs.current[i] = el)}
          geometry={geos[s.kind]}
          position={[s.x, s.y, s.z]}
          scale={s.s}
          renderOrder={0}
        >
          <meshBasicMaterial
            color={s.c}
            transparent
            opacity={0.85}
            depthWrite={false}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  )
}
