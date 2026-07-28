import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { toonGradient, Hull } from './toon.jsx'

// Chubby fairytale serum bottle (h:w ≈ 1.6:1), toon shaded with inverted-hull
// outlines on the opaque parts (liquid, cap). The glass shell stays
// transparent and is sold by anime-style highlight stripes instead of a hull
// (a hull on a transparent shell would show through as dirty fill).

function lathe(points, segments = 96) {
  return new THREE.LatheGeometry(
    points.map(([x, y]) => new THREE.Vector2(x, y)),
    segments
  )
}

const GLASS_PROFILE = [
  [0.001, 0.0],
  [0.34, 0.0],
  [0.56, 0.03],
  [0.67, 0.11],
  [0.715, 0.24],
  [0.72, 0.4],
  [0.72, 1.1], // fat straight body
  [0.705, 1.28], // big soft shoulder
  [0.66, 1.44],
  [0.575, 1.57],
  [0.46, 1.665],
  [0.345, 1.72],
  [0.275, 1.755],
  [0.25, 1.8], // neck
  [0.245, 1.85],
  [0.25, 1.89],
  [0.23, 1.905],
  [0.215, 1.87],
  [0.212, 1.83],
]

const CAP_PROFILE = [
  [0.3, 1.66], // long skirt swallows the neck joint
  [0.325, 1.7],
  [0.34, 1.86],
  [0.335, 2.0],
  [0.31, 2.1],
  [0.26, 2.17],
  [0.18, 2.225],
  [0.08, 2.25],
  [0.001, 2.255], // round dome
]

const LIQUID_PROFILE = [
  [0.001, 0.04],
  [0.3, 0.04],
  [0.51, 0.06],
  [0.615, 0.13],
  [0.655, 0.26],
  [0.66, 0.42],
  [0.66, 0.98],
  [0.65, 1.02],
  [0.6, 1.05],
  [0.001, 1.05],
]

const LAYER_PROFILE = [
  [0.001, 1.05],
  [0.58, 1.05],
  [0.62, 1.08],
  [0.625, 1.12],
  [0.6, 1.155],
  [0.001, 1.155],
]

function SoftStripe({ position, rotation, width, height, opacity }) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: { uO: { value: opacity } },
        vertexShader: /* glsl */ `
          varying vec2 vUv;
          void main() {
            vUv = uv;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: /* glsl */ `
          varying vec2 vUv;
          uniform float uO;
          void main() {
            float x = vUv.x - 0.5;
            float a = exp(-x * x * 26.0);
            a *= smoothstep(0.0, 0.28, vUv.y) * smoothstep(1.0, 0.72, vUv.y);
            gl_FragColor = vec4(vec3(1.0), a * uO);
            #include <tonemapping_fragment>
            #include <colorspace_fragment>
          }
        `,
      }),
    [opacity]
  )
  return (
    <mesh position={position} rotation={rotation} renderOrder={7} material={mat}>
      <planeGeometry args={[width, height]} />
    </mesh>
  )
}

const BUBBLES = [
  { r: 0.03, x: 0.3, z: 0.18, speed: 0.1, off: 0.0 },
  { r: 0.022, x: -0.24, z: 0.3, speed: 0.14, off: 0.35 },
  { r: 0.034, x: -0.1, z: -0.28, speed: 0.08, off: 0.6 },
  { r: 0.02, x: 0.16, z: -0.12, speed: 0.16, off: 0.15 },
  { r: 0.026, x: 0.4, z: -0.05, speed: 0.12, off: 0.8 },
]

export default function Bottle() {
  const glassGeo = useMemo(() => lathe(GLASS_PROFILE), [])
  const capGeo = useMemo(() => lathe(CAP_PROFILE), [])
  const liquidGeo = useMemo(() => lathe(LIQUID_PROFILE), [])
  const layerGeo = useMemo(() => lathe(LAYER_PROFILE), [])
  const bubbleRefs = useRef([])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    BUBBLES.forEach((b, i) => {
      const m = bubbleRefs.current[i]
      if (!m) return
      const y = 0.15 + ((t * b.speed + b.off) % 0.85)
      m.position.set(b.x + Math.sin(t * 0.8 + b.off * 9.0) * 0.03, y, b.z)
      const fade = Math.min(1, (1.0 - y) * 6)
      m.scale.setScalar(Math.max(0.001, fade))
    })
  })

  return (
    <group>
      {/* liquid (opaque toon; depthWrite off so orbs/swirl inside pass depth) */}
      <mesh geometry={liquidGeo} renderOrder={1}>
        <meshToonMaterial color="#ff9ec2" gradientMap={toonGradient} depthWrite={false} />
      </mesh>
      <Hull geometry={liquidGeo} thickness={0.014} renderOrder={0} />

      {/* lighter top layer -> dreamy stratified gradient */}
      <mesh geometry={layerGeo} renderOrder={1} position={[0, 0.004, 0]}>
        <meshToonMaterial color="#ffc9dd" gradientMap={toonGradient} depthWrite={false} />
      </mesh>

      {/* glowing surface */}
      <mesh position={[0, 1.162, 0]} rotation={[-Math.PI / 2, 0, 0]} renderOrder={2}>
        <circleGeometry args={[0.575, 64]} />
        <meshBasicMaterial color={new THREE.Color(1.18, 1.02, 1.12)} toneMapped={false} depthWrite={false} />
      </mesh>

      {/* tilted swirl band inside the liquid */}
      <mesh position={[0, 0.6, 0]} rotation={[Math.PI / 2 + 0.22, 0, 0.15]} renderOrder={3}>
        <torusGeometry args={[0.46, 0.05, 16, 96]} />
        <meshToonMaterial color="#ffd6e6" gradientMap={toonGradient} depthTest={false} depthWrite={false} />
      </mesh>

      {/* rising bubbles */}
      {BUBBLES.map((b, i) => (
        <mesh key={i} ref={(el) => (bubbleRefs.current[i] = el)} renderOrder={3.5}>
          <sphereGeometry args={[b.r, 16, 16]} />
          <meshBasicMaterial color={new THREE.Color(1.25, 1.12, 1.2)} toneMapped={false} depthTest={false} depthWrite={false} />
        </mesh>
      ))}

      {/* gold dome cap + knob */}
      <mesh geometry={capGeo} renderOrder={2}>
        <meshToonMaterial color="#f5cf87" gradientMap={toonGradient} />
      </mesh>
      <Hull geometry={capGeo} thickness={0.013} renderOrder={1.5} />
      <mesh position={[0, 2.30, 0]} renderOrder={2}>
        <sphereGeometry args={[0.062, 32, 32]} />
        <meshToonMaterial color="#f7d68f" gradientMap={toonGradient} />
      </mesh>
      <mesh position={[0, 2.30, 0]} renderOrder={1.5}>
        <sphereGeometry args={[0.074, 32, 32]} />
        <meshBasicMaterial color="#8a5a6a" side={THREE.BackSide} />
      </mesh>

      {/* transparent toon glass shell (no hull — see header note) */}
      <mesh geometry={glassGeo} renderOrder={6}>
        <meshToonMaterial
          color="#ffeef4"
          gradientMap={toonGradient}
          transparent
          opacity={0.36}
          depthWrite={false}
        />
      </mesh>

      {/* anime glass highlights: soft shader stripes, no hard edges */}
      <SoftStripe position={[-0.46, 0.85, 0.53]} rotation={[0, -0.45, 0.05]} width={0.3} height={1.5} opacity={0.55} />
      <SoftStripe position={[0.52, 1.3, 0.4]} rotation={[0, 0.55, -0.4]} width={0.16} height={0.55} opacity={0.4} />
    </group>
  )
}
