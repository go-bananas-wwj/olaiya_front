import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { Hull } from './toon.jsx'

// Chubby toon clouds: merged-look clusters of white toon spheres with a soft
// pink inverted-hull outline, drifting on infinite loops at different depths.

const CLOUDS = [
  {
    x: -4.2, y: 3.4, z: -5.5, speed: 0.1, scale: 1.0,
    blobs: [[0, 0, 0, 0.5], [0.5, 0.06, 0, 0.36], [-0.52, 0.04, 0, 0.38], [0.12, 0.28, 0, 0.34], [-0.18, 0.24, 0, 0.3]],
  },
  {
    x: 3.6, y: 4.4, z: -7, speed: -0.07, scale: 1.35,
    blobs: [[0, 0, 0, 0.55], [0.58, 0.05, 0, 0.4], [-0.55, 0.08, 0, 0.42], [0.2, 0.32, 0, 0.36], [-0.25, 0.3, 0, 0.33]],
  },
  {
    x: -0.8, y: 5.4, z: -8.5, speed: 0.05, scale: 1.7,
    blobs: [[0, 0, 0, 0.5], [0.52, 0.04, 0, 0.38], [-0.5, 0.06, 0, 0.4], [0.1, 0.3, 0, 0.35]],
  },
  {
    x: 5.8, y: 2.9, z: -4.5, speed: -0.13, scale: 0.75,
    blobs: [[0, 0, 0, 0.48], [0.45, 0.05, 0, 0.34], [-0.44, 0.03, 0, 0.35], [0.05, 0.26, 0, 0.3]],
  },
]

const SPAN = 9 // drift half-width before wrapping

export default function Clouds() {
  const refs = useRef([])
  const sphereGeo = useMemo(() => new THREE.SphereGeometry(1, 28, 28), [])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    CLOUDS.forEach((c, i) => {
      const g = refs.current[i]
      if (!g) return
      let x = (c.x + t * c.speed) % (SPAN * 2)
      if (x < -SPAN) x += SPAN * 2
      g.position.x = x
      g.position.y = c.y + Math.sin(t * 0.3 + i * 2.1) * 0.08
    })
  })

  return (
    <group>
      {CLOUDS.map((c, i) => (
        <group key={i} ref={(el) => (refs.current[i] = el)} position={[c.x, c.y, c.z]} scale={c.scale}>
          {c.blobs.map(([bx, by, bz, br], j) => (
            <group key={j} position={[bx, by, bz]}>
              {/* flat basic material keeps the anime clouds clean white —
                  toon shading turned their undersides dingy gray */}
              <mesh geometry={sphereGeo} scale={br}>
                <meshBasicMaterial color="#fef7fb" />
              </mesh>
              <Hull geometry={sphereGeo} thickness={0.024} color="#f0d2e0" scale={br} />
            </group>
          ))}
        </group>
      ))}
    </group>
  )
}
