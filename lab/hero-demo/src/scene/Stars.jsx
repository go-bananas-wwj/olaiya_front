import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'

// Ingredient "stars": emissive orbs sized like their concentration, drifting
// inside the liquid with individual phases. VC is the hero (15%).
const STARS = [
  { id: 'vc', r: 0.11, color: [2.6, 2.05, 2.2], y: 0.86, ax: 0.30, az: 0.26, ay: 0.16, fx: 0.21, fz: 0.17, fy: 0.26, p: 0.0 },
  { r: 0.082, color: [2.3, 1.8, 2.0], y: 0.62, ax: 0.26, az: 0.24, ay: 0.13, fx: 0.26, fz: 0.22, fy: 0.19, p: 1.3 },
  { r: 0.072, color: [2.4, 2.35, 2.4], y: 1.12, ax: 0.28, az: 0.22, ay: 0.10, fx: 0.19, fz: 0.24, fy: 0.22, p: 2.1 },
  { r: 0.064, color: [2.2, 1.7, 1.95], y: 0.40, ax: 0.22, az: 0.26, ay: 0.12, fx: 0.30, fz: 0.20, fy: 0.25, p: 3.4 },
  { r: 0.056, color: [2.45, 2.3, 2.35], y: 1.02, ax: 0.25, az: 0.27, ay: 0.14, fx: 0.23, fz: 0.28, fy: 0.17, p: 4.2 },
  { r: 0.050, color: [2.15, 1.65, 1.9], y: 0.76, ax: 0.27, az: 0.21, ay: 0.15, fx: 0.28, fz: 0.25, fy: 0.21, p: 5.1 },
  { r: 0.044, color: [2.35, 2.3, 2.4], y: 1.22, ax: 0.20, az: 0.23, ay: 0.08, fx: 0.32, fz: 0.27, fy: 0.24, p: 5.9 },
  { r: 0.040, color: [2.1, 1.6, 1.85], y: 0.28, ax: 0.23, az: 0.20, ay: 0.09, fx: 0.25, fz: 0.30, fy: 0.28, p: 2.7 },
]

export default function Stars() {
  const refs = useRef([])

  const materials = useMemo(
    () =>
      STARS.map((s) => {
        // depthTest off: the liquid is opaque (must be, to enter the
        // refraction buffer), so stars draw over it to stay visible inside
        const m = new THREE.MeshBasicMaterial({ toneMapped: false, depthTest: false })
        m.color = new THREE.Color(...s.color)
        return m
      }),
    []
  )

  useFrame((state) => {
    const t = state.clock.elapsedTime
    STARS.forEach((s, i) => {
      const m = refs.current[i]
      if (!m) return
      m.position.set(
        s.ax * Math.sin(t * s.fx + s.p),
        s.y + s.ay * Math.sin(t * s.fy + s.p * 1.7),
        s.az * Math.cos(t * s.fz + s.p * 0.6)
      )
    })
  })

  return (
    <group>
      {STARS.map((s, i) => (
        <mesh
          key={s.id || i}
          ref={(el) => (refs.current[i] = el)}
          material={materials[i]}
          renderOrder={5}
        >
          <sphereGeometry args={[s.r, 32, 32]} />
          {s.id === 'vc' && (
            <Html
              position={[0.2, 0.06, 0]}
              center={false}
              zIndexRange={[8, 0]}
              style={{ pointerEvents: 'none' }}
              wrapperClass="vc-label-wrap"
            >
              <div className="vc-label">VC · 15% 抗坏血酸</div>
            </Html>
          )}
        </mesh>
      ))}
    </group>
  )
}
