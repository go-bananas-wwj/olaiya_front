import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// Window light v2: beams now enter from the RIGHT side of the window and
// slant down-left past the bottle's right flank onto the tabletop — the
// bottle's front (and its ingredient orbs) stays completely clear of them.
// Each blade is a soft gradient plane aligned to its own start->land vector.

const BEAMS = [
  // grazing beam: kisses the bottle's right silhouette (clears the front
  // by geometry — closest approach ~1.0 > bottle radius 0.72)
  { start: [1.9, 2.0, -3.4], land: [0.95, 0.0, 0.35], w: 0.36, o: 0.2, p: 0.0 },
  // main beam, right of the bottle
  { start: [2.8, 2.2, -3.4], land: [1.6, 0.0, 0.7], w: 0.5, o: 0.24, p: 2.1 },
  // far-right accent beam
  { start: [3.5, 1.8, -3.4], land: [2.25, 0.0, 1.1], w: 0.3, o: 0.15, p: 4.2 },
]

const DUST = 22

function bladeMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: { uO: { value: 0.2 }, uT: { value: 0 }, uP: { value: 0 } },
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
      uniform float uT;
      uniform float uP;
      void main() {
        float x = vUv.x - 0.5;
        float across = exp(-x * x * 9.0);
        float along = smoothstep(0.0, 0.3, vUv.y) * smoothstep(1.0, 0.55, vUv.y);
        float breathe = 0.85 + 0.15 * sin(uT * 0.5 + uP);
        float a = across * along * uO * breathe;
        gl_FragColor = vec4(vec3(1.0, 0.93, 0.85), a);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  })
}

const patchVert = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const patchFrag = /* glsl */ `
  varying vec2 vUv;
  uniform float uO;
  uniform float uT;
  uniform float uP;
  void main() {
    vec2 p = (vUv - 0.5) * vec2(2.0, 2.0);
    float a = exp(-dot(p, p) * 3.2) * uO * (0.85 + 0.15 * sin(uT * 0.5 + uP));
    gl_FragColor = vec4(vec3(1.0, 0.94, 0.86), a);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

export default function WindowLight() {
  const beams = useMemo(
    () =>
      BEAMS.map((b) => {
        const start = new THREE.Vector3(...b.start)
        const land = new THREE.Vector3(...b.land)
        const dir = land.clone().sub(start)
        const len = dir.length()
        const mid = start.clone().add(land).multiplyScalar(0.5)
        const quat = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 1, 0),
          dir.normalize()
        )
        const mat = bladeMaterial()
        mat.uniforms.uO.value = b.o
        mat.uniforms.uP.value = b.p
        return { ...b, mid, quat, len, mat }
      }),
    []
  )

  const patches = useMemo(
    () =>
      beams.map((b) => {
        const mat = new THREE.ShaderMaterial({
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
          uniforms: { uO: { value: b.o * 0.6 }, uT: { value: 0 }, uP: { value: b.p } },
          vertexShader: patchVert,
          fragmentShader: patchFrag,
        })
        return { x: b.land[0], z: b.land[2], w: b.w * 1.45, h: b.w * 1.0, mat }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  )

  const dustRef = useRef()
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const dust = useMemo(
    () =>
      Array.from({ length: DUST }, (_, i) => ({
        x: 1.55 + Math.random() * 0.95,
        y0: 0.05 + Math.random() * 1.0,
        z: -2.6 + Math.random() * 2.4,
        sp: 0.05 + Math.random() * 0.09,
        s: 0.008 + Math.random() * 0.011,
        p: i * 1.31,
      })),
    []
  )

  useFrame((state) => {
    const t = state.clock.elapsedTime
    beams.forEach((b) => (b.mat.uniforms.uT.value = t))
    patches.forEach((p) => (p.mat.uniforms.uT.value = t))
    const mesh = dustRef.current
    if (mesh) {
      dust.forEach((d, i) => {
        const y = 0.04 + ((d.y0 + t * d.sp) % 1.05)
        const fade = Math.min(1, (1.09 - y) * 5) * Math.min(1, y * 8)
        dummy.position.set(d.x + Math.sin(t * 0.6 + d.p) * 0.05, y, d.z)
        dummy.scale.setScalar(Math.max(0.0005, d.s * fade))
        dummy.rotation.set(0, 0, 0)
        dummy.updateMatrix()
        mesh.setMatrixAt(i, dummy.matrix)
      })
      mesh.instanceMatrix.needsUpdate = true
    }
  })

  return (
    <group>
      {beams.map((b, i) => (
        <mesh key={i} position={b.mid} quaternion={b.quat} material={b.mat} renderOrder={2}>
          <planeGeometry args={[b.w, b.len]} />
        </mesh>
      ))}

      {patches.map((p, i) => (
        <mesh key={`p${i}`} position={[p.x, 0.006, p.z]} rotation={[-Math.PI / 2, 0, 0]} material={p.mat} renderOrder={2}>
          <planeGeometry args={[p.w, p.h]} />
        </mesh>
      ))}

      <instancedMesh ref={dustRef} args={[undefined, undefined, DUST]} renderOrder={3}>
        <circleGeometry args={[1, 8]} />
        <meshBasicMaterial color="#fff5e6" transparent opacity={0.55} blending={THREE.AdditiveBlending} depthWrite={false} />
      </instancedMesh>
    </group>
  )
}
