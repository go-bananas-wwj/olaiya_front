import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// Window light: 2-3 soft blade beams slanting from the window down onto the
// tabletop, matching bright patches where they land, and slow light-dust
// motes that live only inside the beams.

const BLADES = [
  { x: 0.0, w: 0.34, o: 0.2, tilt: -1.13, p: 0.0 },
  { x: 0.7, w: 0.5, o: 0.24, tilt: -1.13, p: 2.1 },
  { x: 1.4, w: 0.32, o: 0.17, tilt: -1.13, p: 4.2 },
]

const PATCHES = [
  { x: 0.05, z: 0.55, w: 0.62, h: 0.4, o: 0.17, p: 0.0 },
  { x: 0.78, z: 0.7, w: 0.85, h: 0.5, o: 0.22, p: 2.1 },
  { x: 1.5, z: 0.5, w: 0.55, h: 0.36, o: 0.15, p: 4.2 },
]

const DUST = 22

function bladeMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uO: { value: 0.2 },
      uT: { value: 0 },
      uP: { value: 0 },
    },
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

export default function WindowLight() {
  const blades = useMemo(
    () => BLADES.map((b) => ({ ...b, mat: bladeMaterial() })),
    []
  )
  const patchMats = useMemo(
    () =>
      PATCHES.map(
        (p) =>
          new THREE.ShaderMaterial({
            transparent: true,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            uniforms: { uO: { value: p.o }, uT: { value: 0 }, uP: { value: p.p } },
            vertexShader: blades[0].mat.vertexShader,
            fragmentShader: /* glsl */ `
              varying vec2 vUv;
              uniform float uO;
              uniform float uT;
              uniform float uP;
              void main() {
                vec2 p = (vUv - 0.5) * vec2(2.0, 2.0);
                float a = exp(-dot(p, p) * 2.2) * uO * (0.85 + 0.15 * sin(uT * 0.5 + uP));
                gl_FragColor = vec4(vec3(1.0, 0.94, 0.86), a);
                #include <tonemapping_fragment>
                #include <colorspace_fragment>
              }
            `,
          })
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  )

  const dustRef = useRef()
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const dust = useMemo(
    () =>
      Array.from({ length: DUST }, (_, i) => ({
        x: 0.35 + Math.random() * 0.9,
        y0: 0.05 + Math.random() * 1.0,
        z: -3.1 + Math.random() * 2.2,
        sp: 0.05 + Math.random() * 0.09,
        s: 0.008 + Math.random() * 0.011,
        p: i * 1.31,
      })),
    []
  )

  useFrame((state) => {
    const t = state.clock.elapsedTime
    blades.forEach((b) => {
      b.mat.uniforms.uT.value = t
      b.mat.uniforms.uP.value = b.p
    })
    patchMats.forEach((m) => (m.uniforms.uT.value = t))
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
      {/* slanted beams from the window down to the table */}
      {blades.map((b, i) => (
        <mesh key={i} position={[b.x, 0.75, -1.85]} rotation={[b.tilt, 0, 0]} material={b.mat} renderOrder={2}>
          <planeGeometry args={[b.w, 4.2]} />
        </mesh>
      ))}

      {/* bright patches where the beams land */}
      {PATCHES.map((p, i) => (
        <mesh key={`p${i}`} position={[p.x, 0.006, p.z]} rotation={[-Math.PI / 2, 0, 0]} material={patchMats[i]} renderOrder={2}>
          <planeGeometry args={[p.w, p.h]} />
        </mesh>
      ))}

      {/* light dust motes inside the beams */}
      <instancedMesh ref={dustRef} args={[undefined, undefined, DUST]} renderOrder={3}>
        <circleGeometry args={[1, 8]} />
        <meshBasicMaterial color="#fff5e6" transparent opacity={0.55} blending={THREE.AdditiveBlending} depthWrite={false} />
      </instancedMesh>
    </group>
  )
}
