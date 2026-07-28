import { useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { toonGradient } from './toon.jsx'
import { INGREDIENTS, ORBIT } from '../ingredients.js'
import { easeOutBack } from '../sequence.js'

// Ingredient orbs: one signature color + micro-shape each. Hover scales the
// orb 1.3x and pops a cartoon name tag; click opens the evidence card (state
// lifted to App). Raycast targets are fat invisible proxy spheres so hits are
// forgiving while the orbs drift.

function sparkleGeometry() {
  const s = new THREE.Shape()
  s.moveTo(0, 1)
  s.quadraticCurveTo(0.14, 0.14, 1, 0)
  s.quadraticCurveTo(0.14, -0.14, 0, -1)
  s.quadraticCurveTo(-0.14, -0.14, -1, 0)
  s.quadraticCurveTo(-0.14, 0.14, 0, 1)
  return new THREE.ShapeGeometry(s, 8)
}

const MINIS = [
  { r: 0.055, color: '#ffc9dd', y: 0.52, ax: 0.34, az: 0.28, ay: 0.12, fx: 0.3, fz: 0.24, fy: 0.2, p: 2.7 },
  { r: 0.05, color: '#cdeed6', y: 0.86, ax: 0.3, az: 0.3, ay: 0.14, fx: 0.24, fz: 0.29, fy: 0.17, p: 4.9 },
  { r: 0.045, color: '#e8dff7', y: 0.36, ax: 0.36, az: 0.24, ay: 0.1, fx: 0.27, fz: 0.21, fy: 0.24, p: 1.1 },
]

function OrbCore({ ing }) {
  const geo = useMemo(
    () =>
      ing.shape === 'crystal'
        ? new THREE.IcosahedronGeometry(ing.r, 0)
        : new THREE.SphereGeometry(ing.r, 32, 32),
    [ing]
  )
  return (
    <mesh geometry={geo} renderOrder={8}>
      <meshToonMaterial
        color={ing.color}
        gradientMap={toonGradient}
        emissive={ing.color}
        emissiveIntensity={ing.id === 'vc' ? 1.3 : 1.1}
      />
    </mesh>
  )
}

export default function Stars({ onSelect, selectedId, interactive = true, appeared = true }) {
  const [hoveredId, setHoveredId] = useState(null)
  const groupRefs = useRef({})
  const miniRefs = useRef([])
  const sparkRef = useRef()
  const ringRef = useRef()
  const appearStart = useRef(null)
  const v = useMemo(() => new THREE.Vector3(), [])
  const sparkGeo = useMemo(() => sparkleGeometry(), [])
  const glintGeo = useMemo(() => sparkleGeometry(), [])

  useFrame((state, dt) => {
    const t = state.clock.elapsedTime
    if (typeof window !== 'undefined') window.__orbScreen = window.__orbScreen || {}
    if (appeared && appearStart.current === null) appearStart.current = t

    INGREDIENTS.forEach((ing, i) => {
      const o = ORBIT[ing.id]
      const g = groupRefs.current[ing.id]
      if (!g || !o) return
      g.position.set(
        o.ax * Math.sin(t * o.fx + o.p),
        o.y + o.ay * Math.sin(t * o.fy + o.p * 1.7),
        o.az * Math.cos(t * o.fz + o.p * 0.6)
      )
      // P2 pop-in: staggered easeOutBack from 0; until then stay invisible
      let pop = 0.0001
      if (appearStart.current !== null) {
        const raw = THREE.MathUtils.clamp((t - appearStart.current - i * 0.07) / 0.35, 0, 1)
        pop = Math.max(0.0001, easeOutBack(raw))
      }
      const base = hoveredId === ing.id ? 1.3 : selectedId === ing.id ? 1.15 : 1
      const s = THREE.MathUtils.damp(g.scale.x, base * pop, 9, dt)
      g.scale.setScalar(s)

      v.setFromMatrixPosition(g.matrixWorld).project(state.camera)
      window.__orbScreen[ing.id] = [
        Math.round((v.x * 0.5 + 0.5) * state.size.width),
        Math.round((-v.y * 0.5 + 0.5) * state.size.height),
      ]
    })

    MINIS.forEach((m, i) => {
      const g = miniRefs.current[i]
      if (!g) return
      g.position.set(
        m.ax * Math.sin(t * m.fx + m.p),
        m.y + m.ay * Math.sin(t * m.fy + m.p * 1.7),
        m.az * Math.cos(t * m.fz + m.p * 0.6)
      )
      let pop = 0.0001
      if (appearStart.current !== null) {
        const raw = THREE.MathUtils.clamp((t - appearStart.current - 0.35 - i * 0.06) / 0.35, 0, 1)
        pop = Math.max(0.0001, easeOutBack(raw))
      }
      g.scale.setScalar(pop)
    })

    if (sparkRef.current) {
      sparkRef.current.rotation.z = t * 0.9
      const p = 1 + Math.sin(t * 2.2) * 0.12
      sparkRef.current.scale.setScalar(0.17 * p)
    }
    if (ringRef.current) ringRef.current.rotation.z = Math.sin(t * 0.6) * 0.35
  })

  return (
    <group>
      {INGREDIENTS.map((ing) => (
        <group
          key={ing.id}
          ref={(el) => (groupRefs.current[ing.id] = el)}
          onPointerOver={(e) => {
            if (!interactive) return
            e.stopPropagation()
            setHoveredId(ing.id)
            document.body.style.cursor = 'pointer'
          }}
          onPointerOut={() => {
            setHoveredId((h) => (h === ing.id ? null : h))
            document.body.style.cursor = 'auto'
          }}
          onClick={(e) => {
            if (!interactive) return
            e.stopPropagation()
            onSelect(ing.id)
          }}
        >
          {/* fat invisible raycast proxy */}
          <mesh renderOrder={8}>
            <sphereGeometry args={[ing.r * 2.0, 12, 12]} />
            <meshBasicMaterial transparent opacity={0} depthWrite={false} />
          </mesh>

          <OrbCore ing={ing} />

          {/* micro-shapes per ingredient */}
          {ing.shape === 'sparkle' && (
            <mesh ref={sparkRef} geometry={sparkGeo} position={[ing.r * 1.15, ing.r * 1.25, ing.r * 0.4]} renderOrder={9}>
              <meshBasicMaterial color={new THREE.Color(1.9, 1.75, 1.5)} toneMapped={false} side={THREE.DoubleSide} />
            </mesh>
          )}
          {ing.shape === 'ring' && (
            <mesh ref={ringRef} rotation={[1.25, 0, 0]} renderOrder={8}>
              <torusGeometry args={[ing.r * 1.5, ing.r * 0.13, 12, 48]} />
              <meshToonMaterial color={ing.color} gradientMap={toonGradient} emissive={ing.color} emissiveIntensity={0.7} />
            </mesh>
          )}
          {ing.shape === 'glint' && (
            <mesh geometry={glintGeo} position={[ing.r * 0.85, ing.r * 0.9, ing.r * 0.55]} scale={0.055} renderOrder={9}>
              <meshBasicMaterial color="#ffffff" transparent opacity={0.95} side={THREE.DoubleSide} />
            </mesh>
          )}

          {hoveredId === ing.id && (
            <Html
              position={[0, ing.r + 0.22, 0]}
              center
              zIndexRange={[8, 0]}
              style={{ pointerEvents: 'none' }}
              wrapperClass="orb-tag-wrap"
            >
              <div className="orb-tag" style={{ '--c': ing.color }}>
                {ing.name}
              </div>
            </Html>
          )}
        </group>
      ))}

      {/* decorative minis, non-interactive */}
      {MINIS.map((m, i) => (
        <group key={i} ref={(el) => (miniRefs.current[i] = el)}>
          <mesh renderOrder={8}>
            <sphereGeometry args={[m.r, 24, 24]} />
            <meshToonMaterial color={m.color} gradientMap={toonGradient} emissive={m.color} emissiveIntensity={0.9} />
          </mesh>
        </group>
      ))}
    </group>
  )
}
