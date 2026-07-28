import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'

const vertexShader = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

// Pearlescent mesh-gradient backdrop: mother-of-pearl base with slow
// drifting iridescent blobs + animated film grain. Palette is authored in
// sRGB then converted to linear so the composer's output transform is exact.
const fragmentShader = /* glsl */ `
  varying vec2 vUv;
  uniform float uTime;
  uniform float uAspect;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  void main() {
    vec2 uv = vUv;
    vec2 p = (uv - 0.5) * vec2(uAspect, 1.0);

    // linear-space palette
    vec3 base = vec3(0.894, 0.845, 0.793);   // #f3ede6 mother-of-pearl
    vec3 pink = vec3(0.902, 0.539, 0.674);   // #f4c2d7
    vec3 teal = vec3(0.539, 0.728, 0.668);   // #c2ded6
    vec3 lav  = vec3(0.683, 0.587, 0.870);   // #d8caf0
    vec3 gold = vec3(0.854, 0.643, 0.551);   // soft champagne-rose

    float t = uTime;

    vec2 c1 = vec2( 0.42 + 0.26 * sin(t * 0.110 + 0.0),  0.14 + 0.20 * cos(t * 0.130 + 1.7));
    vec2 c2 = vec2(-0.38 + 0.24 * sin(t * 0.090 + 2.3),  0.22 + 0.18 * sin(t * 0.120 + 0.4));
    vec2 c3 = vec2( 0.06 + 0.28 * cos(t * 0.070 + 4.0), -0.24 + 0.16 * sin(t * 0.100 + 2.9));
    vec2 c4 = vec2(-0.24 + 0.20 * cos(t * 0.080 + 1.1), -0.02 + 0.22 * cos(t * 0.060 + 5.2));

    float b1 = exp(-pow(length(p - c1), 2.0) * 2.6);
    float b2 = exp(-pow(length(p - c2), 2.0) * 3.0);
    float b3 = exp(-pow(length(p - c3), 2.0) * 2.4);
    float b4 = exp(-pow(length(p - c4), 2.0) * 3.6);

    vec3 col = base;
    col = mix(col, pink, b1 * 0.62);
    col = mix(col, teal, b2 * 0.58);
    col = mix(col, lav,  b3 * 0.55);
    col = mix(col, gold, b4 * 0.38);

    // animated film grain
    float g = hash(uv * vec2(1548.0, 967.0) + fract(t * 0.731) * 11.17);
    col += (g - 0.5) * 0.024;

    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

export default function PearlBackdrop() {
  const group = useRef()
  const mat = useRef()
  const { camera, size } = useThree()

  const { w, h, dist } = useMemo(() => {
    const dist = 16
    const fov = (camera.fov * Math.PI) / 180
    const h = 2 * Math.tan(fov / 2) * dist * 1.3
    return { w: h * (size.width / size.height), h, dist }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size.width, size.height])

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uAspect: { value: w / h },
    }),
    [w, h]
  )

  useFrame((state) => {
    // glue the backdrop to the camera so parallax never reveals an edge
    group.current.position.copy(camera.position)
    group.current.quaternion.copy(camera.quaternion)
    mat.current.uniforms.uTime.value = state.clock.elapsedTime
  })

  return (
    <group ref={group} renderOrder={-10}>
      <mesh position={[0, 0, -dist]} frustumCulled={false}>
        <planeGeometry args={[w, h, 1, 1]} />
        <shaderMaterial
          ref={mat}
          vertexShader={vertexShader}
          fragmentShader={fragmentShader}
          uniforms={uniforms}
          depthWrite={false}
        />
      </mesh>
    </group>
  )
}
