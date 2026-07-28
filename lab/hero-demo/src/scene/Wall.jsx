import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// Interior wall with a window opening, and the world outside it.
// Layout along z: backstop(-4.30) < sky(-4.00) < outdoor bokeh(-3.95)
//   < clouds(-3.90) < sakura branch(-3.85) < wall pieces with opening(-3.80)
// The window frame/casement itself lives in WindowFrame.jsx at z ≈ -3.7.
//
// Opening rect: x ∈ [-0.7, 2.1], y ∈ [0.55, 2.85]  (w 2.8 × h 2.3)

// Opening rect: x ∈ [1.5, 4.3], y ∈ [0.55, 2.85]  (w 2.8 × h 2.3)
// shifted right so the frame's left edge clears the centered bottle
// (bottle right edge ≈ 0.85 incl. float/rim -> ~0.6 world of daylight)
export const OPENING = { x0: 1.45, x1: 4.05, y0: 0.55, y1: 2.85, z: -3.8 }

// warm plaster, one step deeper than mother-of-pearl (#e8ddd2), subtle grain
const plasterVert = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vWorld;
  void main() {
    vUv = uv;
    vec4 w = modelMatrix * vec4(position, 1.0);
    vWorld = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`
const plasterFrag = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vWorld;
  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }
  void main() {
    vec3 col = vec3(0.808, 0.720, 0.642); // #e8ddd2 in linear
    // gentle top-down lightening
    col *= 0.94 + 0.10 * clamp(vWorld.y / 4.0, 0.0, 1.0);
    // plaster grain
    float g = hash(floor(vWorld.xy * 90.0));
    col += (g - 0.5) * 0.028;
    // soft corner shading so the window reads as the light center
    float d = length(vWorld.xy - vec2(2.75, 1.7)) / 9.0;
    col *= 1.0 - min(0.16, d * 0.16);
    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

const skyFrag = /* glsl */ `
  varying vec2 vUv;
  uniform float uTime;
  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }
  void main() {
    vec3 bot = vec3(0.894, 0.845, 0.793);  // #f3ede6
    vec3 mid = vec3(0.921, 0.691, 0.757);  // #f6d9e2
    vec3 top = vec3(0.713, 0.611, 0.870);  // #dccdf0
    vec3 col = mix(bot, mid, smoothstep(0.0, 0.55, vUv.y));
    col = mix(col, top, smoothstep(0.45, 1.02, vUv.y));
    // faint drifting iridescence
    vec2 p = (vUv - 0.5) * vec2(2.0, 1.6);
    vec2 c1 = vec2(0.3 + 0.2 * sin(uTime * 0.10), 0.1 + 0.15 * cos(uTime * 0.13 + 1.7));
    vec2 c2 = vec2(-0.3 + 0.2 * sin(uTime * 0.08 + 2.3), -0.2 + 0.14 * sin(uTime * 0.11 + 0.4));
    col = mix(col, vec3(0.902, 0.539, 0.674), exp(-dot(p - c1, p - c1) * 2.4) * 0.28);
    col = mix(col, vec3(0.683, 0.587, 0.870), exp(-dot(p - c2, p - c2) * 2.0) * 0.26);
    float g = hash(vUv * vec2(720.0, 450.0) + fract(uTime * 0.731) * 11.17);
    col += (g - 0.5) * 0.02;
    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

const CLOUDS_OUT = [
  { x: 1.15, y: 2.3, s: 0.5, sp: 0.06, blobs: [[0, 0, 0.5], [0.5, 0.05, 0.36], [-0.5, 0.04, 0.38], [0.1, 0.26, 0.32]] },
  { x: 3.25, y: 1.9, s: 0.62, sp: 0.045, blobs: [[0, 0, 0.55], [0.55, 0.05, 0.4], [-0.52, 0.06, 0.4], [0.15, 0.3, 0.34], [-0.2, 0.26, 0.3]] },
  { x: 2.45, y: 2.6, s: 0.38, sp: 0.075, blobs: [[0, 0, 0.48], [0.42, 0.04, 0.32], [-0.4, 0.03, 0.33]] },
]

const BOKEH_OUT = [
  { x: 1.85, y: 1.2, r: 0.16, c: '#ffffff', o: 0.25, sp: 0.3, p: 0 },
  { x: 3.65, y: 2.4, r: 0.22, c: '#f8d8e8', o: 0.28, sp: 0.22, p: 1.3 },
  { x: 2.65, y: 0.9, r: 0.12, c: '#e0d4f4', o: 0.3, sp: 0.26, p: 2.6 },
  { x: 3.95, y: 1.5, r: 0.14, c: '#ffffff', o: 0.22, sp: 0.34, p: 3.2 },
  { x: 2.25, y: 2.5, r: 0.18, c: '#fdf3e2', o: 0.24, sp: 0.2, p: 4.1 },
]

function Plaster({ w, h, position }) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: plasterVert,
        fragmentShader: plasterFrag,
      }),
    []
  )
  return (
    <mesh position={position} material={mat}>
      <planeGeometry args={[w, h]} />
    </mesh>
  )
}

// sakura branch silhouette reaching in from the lower-left of the opening
function SakuraBranch() {
  const { branchGeos, blossoms } = useMemo(() => {
    const mk = (pts, r) =>
      new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(...p))), 24, r, 6, false)
    const branchGeos = [
      mk([[-1.15, 0.35, 0], [-0.75, 0.62, 0], [-0.4, 0.95, 0], [-0.02, 1.28, 0]], 0.026),
      mk([[-0.62, 0.78, 0], [-0.42, 1.06, 0], [-0.3, 1.38, 0]], 0.016),
      mk([[-0.25, 1.08, 0], [0.02, 1.3, 0], [0.24, 1.44, 0]], 0.013),
    ]
    // 5-petal blossoms + buds
    const blossoms = [
      { x: -0.05, y: 1.3, s: 0.075 },
      { x: -0.32, y: 1.42, s: 0.06 },
      { x: 0.22, y: 1.46, s: 0.068 },
      { x: -0.55, y: 1.05, s: 0.055 },
      { x: -0.78, y: 0.68, s: 0.05 },
      { x: -0.4, y: 0.98, s: 0.045, bud: true },
      { x: 0.08, y: 1.2, s: 0.04, bud: true },
    ]
    return { branchGeos, blossoms }
  }, [])

  const petalGeo = useMemo(() => new THREE.CircleGeometry(1, 12), [])

  return (
    <group position={[2.05, 0.15, -3.85]}>
      {branchGeos.map((g, i) => (
        <mesh key={i} geometry={g}>
          <meshBasicMaterial color="#7a4a5c" />
        </mesh>
      ))}
      {blossoms.map((b, i) => (
        <group key={`f${i}`} position={[b.x, b.y, 0.01]} scale={b.s}>
          {b.bud ? (
            <mesh geometry={petalGeo}>
              <meshBasicMaterial color="#9c5a70" />
            </mesh>
          ) : (
            <>
              {[0, 1, 2, 3, 4].map((k) => (
                <mesh
                  key={k}
                  geometry={petalGeo}
                  position={[Math.cos((k / 5) * Math.PI * 2) * 0.62, Math.sin((k / 5) * Math.PI * 2) * 0.62, 0]}
                  scale={0.55}
                >
                  <meshBasicMaterial color="#e89ab4" />
                </mesh>
              ))}
              <mesh geometry={petalGeo} scale={0.3}>
                <meshBasicMaterial color="#c06a86" />
              </mesh>
            </>
          )}
        </group>
      ))}
    </group>
  )
}

export default function Wall() {
  const cloudRefs = useRef([])
  const bokehRefs = useRef([])
  const skyMat = useRef()

  const skyUniforms = useMemo(() => ({ uTime: { value: 0 } }), [])
  const sphereGeo = useMemo(() => new THREE.SphereGeometry(1, 20, 20), [])
  const O = OPENING
  const cx = (O.x0 + O.x1) / 2
  const cy = (O.y0 + O.y1) / 2

  useFrame((state) => {
    const t = state.clock.elapsedTime
    skyMat.current && (skyMat.current.uniforms.uTime.value = t)
    CLOUDS_OUT.forEach((c, i) => {
      const g = cloudRefs.current[i]
      if (!g) return
      // drift in one consistent direction, wrap inside the outdoor strip
      let x = c.x + t * c.sp
      x = ((x - 0.4) % 5.4) + 0.4
      g.position.x = x
    })
    BOKEH_OUT.forEach((b, i) => {
      const m = bokehRefs.current[i]
      if (!m) return
      m.position.y = b.y + Math.sin(t * b.sp + b.p) * 0.12
    })
  })

  return (
    <group>
      {/* backstop: plaster-colored plane far behind everything */}
      <mesh position={[0, 2.5, -4.3]}>
        <planeGeometry args={[30, 16]} />
        <meshBasicMaterial color="#e8ddd2" />
      </mesh>

      {/* sky visible through the opening */}
      <mesh position={[cx, cy, -4.0]}>
        <planeGeometry args={[5.6, 3.6]} />
        <shaderMaterial
          ref={skyMat}
          uniforms={skyUniforms}
          vertexShader={plasterVert}
          fragmentShader={skyFrag}
        />
      </mesh>

      {/* distant bokeh outside */}
      {BOKEH_OUT.map((b, i) => (
        <mesh key={`bo${i}`} ref={(el) => (bokehRefs.current[i] = el)} position={[b.x, b.y, -3.95]}>
          <circleGeometry args={[b.r, 24]} />
          <meshBasicMaterial color={b.c} transparent opacity={b.o} depthWrite={false} />
        </mesh>
      ))}

      {/* chubby clouds drifting past the window */}
      {CLOUDS_OUT.map((c, i) => (
        <group key={`c${i}`} ref={(el) => (cloudRefs.current[i] = el)} position={[c.x, c.y, -3.9]} scale={c.s}>
          {c.blobs.map(([bx, by, br], j) => (
            <mesh key={j} geometry={sphereGeo} position={[bx, by, 0]} scale={br}>
              <meshBasicMaterial color="#fef7fb" />
            </mesh>
          ))}
        </group>
      ))}

      <SakuraBranch />

      {/* plaster wall pieces around the opening */}
      <Plaster w={(O.x0 + 14)} h={16} position={[(O.x0 - 14) / 2, 2.5, O.z]} />
      <Plaster w={(14 - O.x1)} h={16} position={[(O.x1 + 14) / 2, 2.5, O.z]} />
      <Plaster w={O.x1 - O.x0} h={16 - O.y1} position={[cx, (O.y1 + 16) / 2 - 0 + 0, O.z]} />
      <Plaster w={O.x1 - O.x0} h={O.y0 + 2} position={[cx, (O.y0 - 2) / 2, O.z]} />
    </group>
  )
}
