import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// Ambient particles:
//  1. indoor floating sparkles & hearts — halved, the window is the story now
//  2. sakura petals drifting IN through the open casement, sailing past the
//     bottle and landing on the table (<= ~1 petal/sec), no more sky-fall

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

const FLOATERS = [
  { kind: 'sparkle', x: -2.5, y: 2.6, z: -1.6, s: 0.13, c: '#f4b8d2', sp: 0.5, p: 0.0 },
  { kind: 'heart', x: -2.2, y: 3.3, z: -2.4, s: 0.09, c: '#e8c8f0', sp: 0.35, p: 3.1 },
  { kind: 'sparkle', x: 1.9, y: 3.1, z: -1.8, s: 0.15, c: '#f9d9a8', sp: 0.45, p: 0.7 },
  { kind: 'sparkle', x: 2.9, y: 0.7, z: -2.2, s: 0.1, c: '#a8d8e8', sp: 0.5, p: 2.8 },
  { kind: 'heart', x: -3.2, y: 2.0, z: -2.6, s: 0.1, c: '#f9d9a8', sp: 0.45, p: 3.6 },
  { kind: 'sparkle', x: 0.4, y: 3.9, z: -3.0, s: 0.09, c: '#c9b8f0', sp: 0.5, p: 2.0 },
]

const PETALS = 10

export default function Particles() {
  const floatRefs = useRef([])
  const petalRef = useRef()
  const geos = useMemo(() => ({ sparkle: sparkleGeo(), heart: heartGeo() }), [])
  const dummy = useMemo(() => new THREE.Object3D(), [])

  // per-petal flight paths: window opening -> past the bottle -> tabletop
  const petals = useMemo(
    () =>
      Array.from({ length: PETALS }, (_, i) => {
        const sx = -0.4 + Math.random() * 2.2 // spawn inside the opening
        const sy = 1.0 + Math.random() * 1.5
        return {
          sx, sy, sz: -3.5,
          ex: THREE.MathUtils.clamp(sx + (Math.random() - 0.5) * 2.4, -1.7, 2.1),
          ez: 0.3 + Math.random() * 1.9,
          life: 8 + Math.random() * 3,
          sway: 2.5 + Math.random() * 2,
          rot: 0.8 + Math.random() * 1.4,
          scale: 0.055 + Math.random() * 0.04,
          off: (i / PETALS) * 1.0,
        }
      }),
    []
  )

  useFrame((state) => {
    const t = state.clock.elapsedTime

    FLOATERS.forEach((s, i) => {
      const m = floatRefs.current[i]
      if (!m) return
      m.position.y = s.y + Math.sin(t * s.sp + s.p) * 0.22
      m.position.x = s.x + Math.sin(t * s.sp * 0.6 + s.p * 2.1) * 0.1
      m.rotation.z = Math.sin(t * s.sp * 0.8 + s.p) * 0.35
    })

    const mesh = petalRef.current
    if (mesh) {
      petals.forEach((f, i) => {
        const u = ((t / f.life + f.off) % 1 + 1) % 1
        const x = THREE.MathUtils.lerp(f.sx, f.ex, u) + Math.sin(u * f.sway * Math.PI * 2 + f.off * 9) * 0.22
        const y = THREE.MathUtils.lerp(f.sy, 0.05, Math.pow(u, 1.15)) + Math.sin(u * Math.PI) * 0.25
        const z = THREE.MathUtils.lerp(f.sz, f.ez, u)
        const land = THREE.MathUtils.clamp((1 - u) / 0.08, 0, 1) // shrink out on the table
        const born = THREE.MathUtils.clamp(u / 0.05, 0, 1)
        dummy.position.set(x, y, z)
        dummy.rotation.set(Math.sin(t * f.rot + f.off * 7) * 0.9, 0, t * f.rot + f.off * 5)
        dummy.scale.setScalar(Math.max(0.0001, f.scale * land * born))
        dummy.updateMatrix()
        mesh.setMatrixAt(i, dummy.matrix)
      })
      mesh.instanceMatrix.needsUpdate = true
    }
  })

  return (
    <group>
      {FLOATERS.map((s, i) => (
        <mesh
          key={i}
          ref={(el) => (floatRefs.current[i] = el)}
          geometry={geos[s.kind]}
          position={[s.x, s.y, s.z]}
          scale={s.s}
          renderOrder={0}
        >
          <meshBasicMaterial color={s.c} transparent opacity={0.85} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      ))}

      <instancedMesh ref={petalRef} args={[geos.heart, undefined, PETALS]} renderOrder={1}>
        <meshBasicMaterial color="#f7b8cd" transparent opacity={0.92} depthWrite={false} side={THREE.DoubleSide} />
      </instancedMesh>
    </group>
  )
}
