import { useMemo } from 'react'
import * as THREE from 'three'

// A soft pearl mist band swallowing the table's far edge so the tabletop
// never reads as floating in mid-air. Pure vertical alpha gradient.
export default function Mist() {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: {
          uC: { value: new THREE.Color('#f7ece4') },
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
          uniform vec3 uC;
          void main() {
            float a = smoothstep(1.0, 0.15, vUv.y);
            gl_FragColor = vec4(uC, a * 0.95);
            #include <tonemapping_fragment>
            #include <colorspace_fragment>
          }
        `,
      }),
    []
  )
  return (
    <mesh position={[0, -0.75, -3.4]} renderOrder={-5} material={mat} frustumCulled={false}>
      <planeGeometry args={[26, 4]} />
    </mesh>
  )
}
