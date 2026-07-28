import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// Ambient particles, three families:
//  1. slow floating sparkles & hearts around the bottle (kept from toon pass)
//  2. distant bokeh discs for airiness
//  3. falling sakura petals & star grains (InstancedMesh, loop, fade on land)

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
]

const BOKEH = [
  { x: -3.4, y: 2.2, z: -5.5, r: 0.42, c: '#ffffff', o: 0.22, sp: 0.3, p: 0 },
  { x: 2.8, y: 3.6, z: -6.5, r: 0.55, c: '#f8d8e8', o: 0.25, sp: 0.22, p: 1.3 },
  { x: -1.8, y: 4.4, z: -7, r: 0.35, c: '#e0d4f4', o: 0.28, sp: 0.26, p: 2.6 },
  { x: 3.8, y: 1.4, z: -5, r: 0.3, c: '#ffffff', o: 0.2, sp: 0.34, p: 3.2 },
  { x: -4.4, y: 3.4, z: -6, r: 0.48, c: '#f0e0f0', o: 0.22, sp: 0.18, p: 4.1 },
  { x: 1.2, y: 4.8, z: -7.5, r: 0.4, c: '#fdf3e2', o: 0.26, sp: 0.24, p: 5.0 },
  { x: 4.6, y: 4.6, z: -8, r: 0.6, c: '#ffffff', o: 0.18, sp: 0.2, p: 5.8 },
  { x: -0.6, y: 1.8, z: -4.5, r: 0.26, c: '#f8d8e8', o: 0.24, sp: 0.3, p: 2.0 },
]

const PETALS = 12
const GRAINS = 8

export default function Particles() {
  const floatRefs = useRef([])
  const bokehRefs = useRef([])
  const petalRef = useRef()
  const grainRef = useRef()
  const geos = useMemo(() => ({ sparkle: sparkleGeo(), heart: heartGeo() }), [])
  const dummy = useMemo(() => new THREE.Object3D(), [])

  const fallers = useMemo(() => {
    const mk = (n, yMin, yMax) =>
      Array.from({ length: n }, (_, i) => ({
        x: -4 + Math.random() * 8,
        z: -2.5 + Math.random() * 3.2,
        y0: yMin + Math.random() * (yMax - yMin),
        speed: 0.22 + Math.random() * 0.25,
        rot: 0.5 + Math.random() * 1.2,
        sway: 0.3 + Math.random() * 0.5,
        scale: 0.05 + Math.random() * 0.05,
        p: i * 1.37,
      }))
    return { petals: mk(PETALS, 3.5, 6.5), grains: mk(GRAINS, 3.5, 6.5) }
  }, [])

  useFrame((state) => {
    const t = state.clock.elapsedTime

    FLOATERS.forEach((s, i) => {
      const m = floatRefs.current[i]
      if (!m) return
      m.position.y = s.y + Math.sin(t * s.sp + s.p) * 0.22
      m.position.x = s.x + Math.sin(t * s.sp * 0.6 + s.p * 2.1) * 0.1
      m.rotation.z = Math.sin(t * s.sp * 0.8 + s.p) * 0.35
    })

    BOKEH.forEach((b, i) => {
      const m = bokehRefs.current[i]
      if (!m) return
      m.position.y = b.y + Math.sin(t * b.sp + b.p) * 0.3
      m.position.x = b.x + Math.sin(t * b.sp * 0.7 + b.p * 1.4) * 0.2
    })

    const drop = (mesh, list, kind) => {
      if (!mesh) return
      list.forEach((f, i) => {
        const span = f.y0 + 0.6
        const y = f.y0 - ((t * f.speed + f.p) % span)
        const land = THREE.MathUtils.clamp((y - 0.02) / 0.35, 0, 1) // shrink out at the tabletop
        dummy.position.set(f.x + Math.sin(t * f.sway + f.p) * 0.35, y, f.z)
        dummy.rotation.set(kind === 'petal' ? Math.sin(t * f.rot + f.p) * 0.9 : 0, 0, t * f.rot + f.p)
        dummy.scale.setScalar(Math.max(0.0001, f.scale * land))
        dummy.updateMatrix()
        mesh.setMatrixAt(i, dummy.matrix)
      })
      mesh.instanceMatrix.needsUpdate = true
    }
    drop(petalRef.current, fallers.petals, 'petal')
    drop(grainRef.current, fallers.grains, 'grain')
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

      {BOKEH.map((b, i) => (
        <mesh key={`b${i}`} ref={(el) => (bokehRefs.current[i] = el)} position={[b.x, b.y, b.z]} renderOrder={-2}>
          <circleGeometry args={[b.r, 32]} />
          <meshBasicMaterial color={b.c} transparent opacity={b.o} depthWrite={false} />
        </mesh>
      ))}

      <instancedMesh ref={petalRef} args={[geos.heart, undefined, PETALS]} renderOrder={1}>
        <meshBasicMaterial color="#f7b8cd" transparent opacity={0.9} depthWrite={false} side={THREE.DoubleSide} />
      </instancedMesh>
      <instancedMesh ref={grainRef} args={[geos.sparkle, undefined, GRAINS]} renderOrder={1}>
        <meshBasicMaterial color="#ffe9a8" transparent opacity={0.85} depthWrite={false} side={THREE.DoubleSide} />
      </instancedMesh>
    </group>
  )
}
