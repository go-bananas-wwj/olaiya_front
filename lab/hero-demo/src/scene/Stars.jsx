import { useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { toonGradient, Hull } from './toon.jsx'
import { INGREDIENTS, ORBIT } from '../ingredients.js'
import { easeOutBack } from '../sequence.js'

// Ingredient orbs v3: recognizable toon miniatures with a jelly wobble,
// soft inverted-hull outlines and gentle glow. Interaction is unchanged:
// fat invisible sphere proxies (r x 2) drive hover tag / click card.

/* ---------- orange-slice face texture (VC) ---------- */
function makeOrangeFace() {
  const c = document.createElement('canvas')
  c.width = c.height = 256
  const g = c.getContext('2d')
  const R = 128
  // rind
  g.fillStyle = '#f08c1e'
  g.beginPath()
  g.arc(R, R, 126, 0, Math.PI * 2)
  g.fill()
  // pith ring
  g.fillStyle = '#ffe9c4'
  g.beginPath()
  g.arc(R, R, 116, 0, Math.PI * 2)
  g.fill()
  // flesh
  const grad = g.createRadialGradient(R, R, 8, R, R, 112)
  grad.addColorStop(0, '#ffc86a')
  grad.addColorStop(1, '#ff9e2e')
  g.fillStyle = grad
  g.beginPath()
  g.arc(R, R, 110, 0, Math.PI * 2)
  g.fill()
  // juice vesicles (short radial streaks per wedge)
  const wedges = 9
  for (let w = 0; w < wedges; w++) {
    const a0 = (w / wedges) * Math.PI * 2
    for (let i = 0; i < 22; i++) {
      const a = a0 + (0.12 + Math.random() * 0.5) * ((Math.PI * 2) / wedges)
      const r0 = 16 + Math.random() * 88
      const r1 = r0 + 4 + Math.random() * 10
      g.strokeStyle = Math.random() > 0.5 ? 'rgba(255,240,200,0.4)' : 'rgba(240,130,20,0.28)'
      g.lineWidth = 1.6
      g.beginPath()
      g.moveTo(R + Math.cos(a) * r0, R + Math.sin(a) * r0)
      g.lineTo(R + Math.cos(a) * r1, R + Math.sin(a) * r1)
      g.stroke()
    }
  }
  // segment membranes
  g.strokeStyle = '#fff0d0'
  g.lineWidth = 5
  g.lineCap = 'round'
  for (let w = 0; w < wedges; w++) {
    const a = (w / wedges) * Math.PI * 2
    g.beginPath()
    g.moveTo(R + Math.cos(a) * 10, R + Math.sin(a) * 10)
    g.lineTo(R + Math.cos(a) * 109, R + Math.sin(a) * 109)
    g.stroke()
  }
  // center pith
  g.fillStyle = '#fff0d0'
  g.beginPath()
  g.arc(R, R, 10, 0, Math.PI * 2)
  g.fill()
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

/* ---------- droplet lathe (VE honey / NA water) ---------- */
function dropletGeo(stretch = 1) {
  const pts = [
    [0.001, 0.0],
    [0.055, 0.004],
    [0.095, 0.026],
    [0.112, 0.062],
    [0.108, 0.098],
    [0.088, 0.132],
    [0.062, 0.162],
    [0.036, 0.187],
    [0.014, 0.208],
    [0.001, 0.218],
  ].map(([x, y]) => new THREE.Vector2(x, y * stretch))
  return new THREE.LatheGeometry(pts, 48)
}

function sparkleGeometry() {
  const s = new THREE.Shape()
  s.moveTo(0, 1)
  s.quadraticCurveTo(0.14, 0.14, 1, 0)
  s.quadraticCurveTo(0.14, -0.14, 0, -1)
  s.quadraticCurveTo(-0.14, -0.14, -1, 0)
  s.quadraticCurveTo(-0.14, 0.14, 0, 1)
  return new THREE.ShapeGeometry(s, 8)
}

/* ---------- per-ingredient miniatures ---------- */

function OrangeSlice({ ing }) {
  const r = ing.r
  const geo = useMemo(() => new THREE.CylinderGeometry(r, r, r * 0.34, 40), [r])
  const face = useMemo(() => makeOrangeFace(), [])
  const mats = useMemo(
    () => [
      new THREE.MeshToonMaterial({ color: '#f08c1e', gradientMap: toonGradient, emissive: '#f08c1e', emissiveIntensity: 0.35 }),
      new THREE.MeshToonMaterial({ map: face, gradientMap: toonGradient, emissive: '#ffab3c', emissiveIntensity: 0.3 }),
      new THREE.MeshToonMaterial({ map: face, gradientMap: toonGradient, emissive: '#ffab3c', emissiveIntensity: 0.3 }),
    ],
    [face]
  )
  return (
    <group rotation={[1.25, 0.35, 0.2]}>
      <mesh geometry={geo} material={mats} renderOrder={8} />
      <Hull geometry={geo} thickness={0.01} renderOrder={7.5} />
      {/* rind glint */}
      <mesh position={[r * 0.55, r * 0.22, r * 0.72]} renderOrder={9}>
        <sphereGeometry args={[r * 0.16, 12, 12]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.8} />
      </mesh>
    </group>
  )
}

function Drop({ ing, stretch, glintY }) {
  const geo = useMemo(() => dropletGeo(stretch), [stretch])
  return (
    <group position={[0, -0.11 * stretch, 0]}>
      <mesh geometry={geo} renderOrder={8}>
        <meshToonMaterial color={ing.color} gradientMap={toonGradient} emissive={ing.color} emissiveIntensity={0.45} />
      </mesh>
      <Hull geometry={geo} thickness={0.01} renderOrder={7.5} />
      {/* inner highlight -> juicy drop */}
      <mesh position={[0.045, glintY, 0.07]} rotation={[0, 0, -0.4]} renderOrder={9}>
        <capsuleGeometry args={[0.016, 0.05, 6, 12]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.75} />
      </mesh>
      <mesh position={[-0.03, 0.05, 0.085]} renderOrder={9}>
        <sphereGeometry args={[0.014, 10, 10]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.6} />
      </mesh>
    </group>
  )
}

function Gem({ ing, sparkGeo }) {
  const outer = useMemo(() => new THREE.IcosahedronGeometry(ing.r, 0), [ing.r])
  const inner = useMemo(() => new THREE.IcosahedronGeometry(ing.r * 0.58, 0), [ing.r])
  return (
    <group>
      <mesh geometry={outer} renderOrder={8}>
        <meshToonMaterial color={ing.color} gradientMap={toonGradient} emissive={ing.color} emissiveIntensity={0.4} flatShading />
      </mesh>
      {/* inner refraction layer */}
      <mesh geometry={inner} renderOrder={8.1}>
        <meshBasicMaterial color="#dcc8ff" transparent opacity={0.55} />
      </mesh>
      <Hull geometry={outer} thickness={0.009} renderOrder={7.5} />
      {/* star glint */}
      <mesh geometry={sparkGeo} position={[ing.r * 0.7, ing.r * 0.75, ing.r * 0.5]} scale={0.05} renderOrder={9}>
        <meshBasicMaterial color={new THREE.Color(1.7, 1.6, 1.9)} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}

function Pearl({ color }) {
  return (
    <group>
      <mesh renderOrder={8}>
        <sphereGeometry args={[1, 28, 28]} />
        <meshToonMaterial color={color} gradientMap={toonGradient} emissive={color} emissiveIntensity={0.35} />
      </mesh>
      <mesh position={[0.32, 0.36, 0.6]} renderOrder={9}>
        <sphereGeometry args={[0.17, 10, 10]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.75} />
      </mesh>
    </group>
  )
}

function OrbBody({ ing, sparkGeo }) {
  switch (ing.shape) {
    case 'sparkle':
      return <OrangeSlice ing={ing} />
    case 'ring':
      return <Drop ing={ing} stretch={1.0} glintY={0.1} />
    case 'crystal':
      return <Gem ing={ing} sparkGeo={sparkGeo} />
    case 'glint':
      return <Drop ing={ing} stretch={0.82} glintY={0.085} />
    default:
      return <Drop ing={ing} stretch={0.9} glintY={0.09} />
  }
}

const MINIS = [
  { r: 0.055, color: '#ffe4ef', y: 0.52, ax: 0.34, az: 0.28, ay: 0.12, fx: 0.3, fz: 0.24, fy: 0.2, p: 2.7 },
  { r: 0.05, color: '#fdf2f8', y: 0.86, ax: 0.3, az: 0.3, ay: 0.14, fx: 0.24, fz: 0.29, fy: 0.17, p: 4.9 },
  { r: 0.045, color: '#efe9fa', y: 0.36, ax: 0.36, az: 0.24, ay: 0.1, fx: 0.27, fz: 0.21, fy: 0.24, p: 1.1 },
]

export default function Stars({ onSelect, selectedId, interactive = true, appeared = true }) {
  const [hoveredId, setHoveredId] = useState(null)
  const groupRefs = useRef({})
  const bodyRefs = useRef({})
  const miniRefs = useRef([])
  const appearStart = useRef(null)
  const v = useMemo(() => new THREE.Vector3(), [])
  const sparkGeo = useMemo(() => sparkleGeometry(), [])

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
      // P2 pop-in
      let pop = 0.0001
      if (appearStart.current !== null) {
        const raw = THREE.MathUtils.clamp((t - appearStart.current - i * 0.07) / 0.35, 0, 1)
        pop = Math.max(0.0001, easeOutBack(raw))
      }
      const base = hoveredId === ing.id ? 1.3 : selectedId === ing.id ? 1.15 : 1
      const s = THREE.MathUtils.damp(g.scale.x, base * pop, 9, dt)
      // jelly wobble on top of the damped scale
      g.scale.set(s * (1 + Math.sin(t * 2.1 + o.p) * 0.03), s * (1 + Math.sin(t * 2.1 + o.p + Math.PI / 2) * 0.035), s)
      g.rotation.z = Math.sin(t * 1.4 + o.p) * 0.05

      // slow tumble for the miniature body
      const body = bodyRefs.current[ing.id]
      if (body) body.rotation.y = t * 0.35 + o.p

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
      g.scale.setScalar(m.r * pop)
    })
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

          <group ref={(el) => (bodyRefs.current[ing.id] = el)}>
            <OrbBody ing={ing} sparkGeo={sparkGeo} />
          </group>

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

      {/* pearls, non-interactive */}
      {MINIS.map((m, i) => (
        <group key={i} ref={(el) => (miniRefs.current[i] = el)} scale={m.r}>
          <Pearl color={m.color} />
        </group>
      ))}
    </group>
  )
}
