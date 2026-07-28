import { useMemo } from 'react'
import * as THREE from 'three'
import { RoundedBox } from '@react-three/drei'

// Light warm wood table, fully procedural: pearl-warm base + faint wavy grain
// streaks + a few soft knots painted into a canvas texture.
function makeWoodTexture() {
  const c = document.createElement('canvas')
  c.width = 1024
  c.height = 512
  const g = c.getContext('2d')

  g.fillStyle = '#f4e3cf'
  g.fillRect(0, 0, 1024, 512)

  // long wavy grain streaks
  for (let i = 0; i < 64; i++) {
    const y0 = Math.random() * 512
    const warm = 165 + (Math.random() * 35) | 0
    g.strokeStyle = `rgba(${warm},${130 + (Math.random() * 25) | 0},${95 + (Math.random() * 25) | 0},${0.08 + Math.random() * 0.09})`
    g.lineWidth = 1 + Math.random() * 3
    g.beginPath()
    g.moveTo(-12, y0)
    for (let x = 0; x <= 1024; x += 42) {
      g.lineTo(x, y0 + Math.sin(x * 0.012 + i * 1.7) * 5 + (Math.random() - 0.5) * 3)
    }
    g.stroke()
  }

  // a few soft knots
  for (let i = 0; i < 5; i++) {
    const x = Math.random() * 1024
    const y = Math.random() * 512
    for (let r = 14; r > 3; r -= 3) {
      g.strokeStyle = `rgba(175,135,100,${0.05 + Math.random() * 0.05})`
      g.lineWidth = 1.4
      g.beginPath()
      g.ellipse(x, y, r * 1.8, r, 0.2, 0, Math.PI * 2)
      g.stroke()
    }
  }

  const tex = new THREE.CanvasTexture(c)
  tex.wrapS = THREE.RepeatWrapping
  tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(1.6, 1)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

export default function Table() {
  const wood = useMemo(() => makeWoodTexture(), [])
  return (
    <RoundedBox args={[14, 0.36, 7]} radius={0.1} smoothness={4} position={[0, -0.18, 1.4]}>
      <meshStandardMaterial map={wood} roughness={0.5} metalness={0} />
    </RoundedBox>
  )
}
