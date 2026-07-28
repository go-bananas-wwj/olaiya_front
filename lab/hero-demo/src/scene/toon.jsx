import { useMemo } from 'react'
import * as THREE from 'three'

// 4-step gradient map -> clean cel bands. Steps are biased bright so the
// shadow step never turns muddy on pastel colors.
export function makeToonGradient(steps = [0.52, 0.72, 0.88, 1.0]) {
  const data = new Uint8Array(steps.map((s) => Math.round(s * 255)))
  const tex = new THREE.DataTexture(data, steps.length, 1, THREE.RedFormat)
  tex.minFilter = THREE.NearestFilter
  tex.magFilter = THREE.NearestFilter
  tex.generateMipmaps = false
  tex.needsUpdate = true
  return tex
}

export const toonGradient = makeToonGradient()

// Inverted-hull outline: push vertices along normals in a tiny shader,
// render BackSide. Constant width regardless of silhouette curvature.
export function Hull({ geometry, thickness = 0.016, color = '#8a5a6a', ...props }) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: {
          uT: { value: thickness },
          uC: { value: new THREE.Color(color) },
        },
        vertexShader: /* glsl */ `
          uniform float uT;
          void main() {
            vec3 p = position + normal * uT;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
          }
        `,
        fragmentShader: /* glsl */ `
          uniform vec3 uC;
          void main() {
            gl_FragColor = vec4(uC, 1.0);
            #include <tonemapping_fragment>
            #include <colorspace_fragment>
          }
        `,
        side: THREE.BackSide,
      }),
    [thickness, color]
  )
  return <mesh geometry={geometry} material={mat} {...props} />
}
