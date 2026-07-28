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

// Fairytale sky: pearl -> soft pink -> pale lavender vertical gradient, slow
// iridescent blobs, two gentle diagonal light shafts, animated film grain.
// Authored in linear space; tonemapping/colorspace chunks keep the pipeline.
const fragmentShader = /* glsl */ `
  varying vec2 vUv;
  uniform float uTime;
  uniform float uAspect;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float shaft(vec2 p, float ang, float off, float w) {
    vec2 d = vec2(cos(ang), sin(ang));
    float x = dot(p, vec2(-d.y, d.x)) + off;
    return smoothstep(w, 0.0, abs(x));
  }

  void main() {
    vec2 uv = vUv;
    vec2 p = (uv - 0.5) * vec2(uAspect, 1.0);
    float t = uTime;

    // sky gradient (linear space): #f3ede6 -> #f6d9e2 -> #dccdf0
    vec3 bot = vec3(0.894, 0.845, 0.793);
    vec3 mid = vec3(0.921, 0.691, 0.757);
    vec3 top = vec3(0.713, 0.611, 0.870);
    vec3 col = mix(bot, mid, smoothstep(0.0, 0.55, uv.y));
    col = mix(col, top, smoothstep(0.45, 1.02, uv.y));

    // soft iridescent blobs
    vec3 pink = vec3(0.902, 0.539, 0.674);
    vec3 teal = vec3(0.539, 0.728, 0.668);
    vec3 lav  = vec3(0.683, 0.587, 0.870);

    vec2 c1 = vec2( 0.40 + 0.24 * sin(t * 0.110 + 0.0),  0.12 + 0.18 * cos(t * 0.130 + 1.7));
    vec2 c2 = vec2(-0.36 + 0.22 * sin(t * 0.090 + 2.3),  0.20 + 0.16 * sin(t * 0.120 + 0.4));
    vec2 c3 = vec2( 0.05 + 0.26 * cos(t * 0.070 + 4.0), -0.22 + 0.15 * sin(t * 0.100 + 2.9));

    float b1 = exp(-pow(length(p - c1), 2.0) * 2.0);
    float b2 = exp(-pow(length(p - c2), 2.0) * 2.4);
    float b3 = exp(-pow(length(p - c3), 2.0) * 1.8);

    col = mix(col, pink, b1 * 0.35);
    col = mix(col, teal, b2 * 0.28);
    col = mix(col, lav,  b3 * 0.30);

    // dreamy light shafts
    col += vec3(1.0, 0.97, 0.94) * shaft(p, 0.55, 0.35 + sin(t * 0.050) * 0.25, 0.30) * 0.10;
    col += vec3(1.0, 0.97, 0.94) * shaft(p, 0.55, -0.45 + sin(t * 0.038 + 2.0) * 0.18, 0.16) * 0.07;

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
