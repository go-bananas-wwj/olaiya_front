import { useMemo } from 'react'
import * as THREE from 'three'
import { toonGradient, Hull } from './toon.jsx'
import { OPENING } from './Wall.jsx'

// Warm wood window: outer frame, 4-pane muntins, and the left casement swung
// ~35° inward. Sits at z ≈ -3.7, in front of the wall opening (z = -3.8).

function makeFrameWood() {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 256
  const g = c.getContext('2d')
  g.fillStyle = '#d9bd9c' // one step deeper than the tabletop
  g.fillRect(0, 0, 512, 256)
  for (let i = 0; i < 30; i++) {
    const y0 = Math.random() * 256
    g.strokeStyle = `rgba(${150 + (Math.random() * 30) | 0},${110 + (Math.random() * 20) | 0},${75 + (Math.random() * 20) | 0},${0.08 + Math.random() * 0.08})`
    g.lineWidth = 1 + Math.random() * 2.4
    g.beginPath()
    g.moveTo(-8, y0)
    for (let x = 0; x <= 512; x += 36) {
      g.lineTo(x, y0 + Math.sin(x * 0.02 + i * 1.3) * 3 + (Math.random() - 0.5) * 2)
    }
    g.stroke()
  }
  const tex = new THREE.CanvasTexture(c)
  tex.wrapS = THREE.RepeatWrapping
  tex.wrapT = THREE.RepeatWrapping
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function Rail({ size, position, wood }) {
  return (
    <mesh position={position}>
      <boxGeometry args={size} />
      <meshToonMaterial map={wood} gradientMap={toonGradient} />
    </mesh>
  )
}

export default function WindowFrame() {
  const wood = useMemo(() => makeFrameWood(), [])
  const O = OPENING
  const W = O.x1 - O.x0 // 2.8
  const H = O.y1 - O.y0 // 2.3
  const cx = (O.x0 + O.x1) / 2
  const cy = (O.y0 + O.y1) / 2
  const z = -3.7
  const T = 0.14 // frame rail thickness
  const D = 0.12 // frame depth

  // casement (left half), hinged at the left jamb
  const caseW = W / 2 - T * 0.75
  const caseH = H - T * 1.1
  const railT = 0.075

  return (
    <group>
      {/* outer frame */}
      <Rail size={[W + T, T, D]} position={[cx, O.y1 + T / 2 - 0.02, z]} wood={wood} />
      <Rail size={[W + T, T, D]} position={[cx, O.y0 - T / 2 + 0.02, z]} wood={wood} />
      <Rail size={[T, H, D]} position={[O.x0 + T / 2 - 0.02, cy, z]} wood={wood} />
      <Rail size={[T, H, D]} position={[O.x1 - T / 2 + 0.02, cy, z]} wood={wood} />
      {/* sill */}
      <Rail size={[W + T + 0.16, 0.08, D + 0.1]} position={[cx, O.y0 - T - 0.02, z + 0.02]} wood={wood} />

      {/* fixed muntins for the right half (left half is the open casement) */}
      <Rail size={[railT, H - T, D * 0.7]} position={[cx + W / 4 - 0.02, cy, z]} wood={wood} />
      <Rail size={[W / 2 - T, railT, D * 0.7]} position={[cx + W / 4, cy, z]} wood={wood} />

      {/* center stile the casement closes against */}
      <Rail size={[T * 0.8, H, D]} position={[cx, cy, z]} wood={wood} />

      {/* open casement: hinge at left jamb, swung ~35° into the room */}
      <group position={[O.x0 + 0.02, cy, z]} rotation={[0, 0.61, 0]}>
        <group position={[caseW / 2 + railT / 2, 0, 0]}>
          {/* casement frame rails */}
          <Rail size={[caseW + railT, railT, 0.09]} position={[0, caseH / 2, 0]} wood={wood} />
          <Rail size={[caseW + railT, railT, 0.09]} position={[0, -caseH / 2, 0]} wood={wood} />
          <Rail size={[railT, caseH, 0.09]} position={[caseW / 2, 0, 0]} wood={wood} />
          <Rail size={[railT, caseH, 0.09]} position={[-caseW / 2, 0, 0]} wood={wood} />
          {/* casement cross muntin */}
          <Rail size={[caseW, railT * 0.7, 0.07]} position={[0, 0, 0]} wood={wood} />
          {/* glass with a soft diagonal sheen */}
          <mesh position={[0, 0, -0.01]}>
            <planeGeometry args={[caseW - 0.04, caseH - 0.04]} />
            <meshBasicMaterial color="#eaf4ff" transparent opacity={0.14} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
          <mesh position={[-0.12, 0.1, 0.005]} rotation={[0, 0, -0.5]}>
            <planeGeometry args={[0.16, caseH * 0.9]} />
            <meshBasicMaterial color="#ffffff" transparent opacity={0.08} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
        </group>
        {/* outline for the swung casement so its silhouette reads */}
        <mesh position={[caseW / 2 + railT / 2, 0, -0.05]}>
          <boxGeometry args={[caseW + railT + 0.03, caseH + railT + 0.03, 0.02]} />
          <meshBasicMaterial color="#8a5a6a" side={THREE.BackSide} transparent opacity={0.9} />
        </mesh>
      </group>
    </group>
  )
}
