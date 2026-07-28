import { useMemo } from 'react'
import * as THREE from 'three'

// SkinCeuticals-CE-style serum bottle: cylindrical body, soft shoulder,
// short neck, brushed-gold dropper cap. All geometry is procedural lathe.

function lathe(points, segments = 96) {
  return new THREE.LatheGeometry(
    points.map(([x, y]) => new THREE.Vector2(x, y)),
    segments
  )
}

const GLASS_PROFILE = [
  [0.001, 0.0],
  [0.26, 0.0],
  [0.42, 0.012],
  [0.485, 0.05],
  [0.50, 0.12],
  [0.505, 0.22],
  [0.505, 1.42], // straight body
  [0.50, 1.50], // quick micro-shoulder
  [0.475, 1.56],
  [0.42, 1.615],
  [0.33, 1.655],
  [0.25, 1.68],
  [0.205, 1.70], // neck
  [0.188, 1.74],
  [0.185, 1.80],
  [0.19, 1.83], // rim
  [0.17, 1.845],
  [0.152, 1.81], // inner lip, hints at wall thickness
  [0.15, 1.76],
]

const CAP_PROFILE = [
  [0.196, 1.66], // skirt bottom inner
  [0.222, 1.68],
  [0.228, 1.76],
  [0.228, 2.06],
  [0.218, 2.13],
  [0.19, 2.185],
  [0.12, 2.215],
  [0.001, 2.225], // domed top
]

const LIQUID_PROFILE = [
  [0.001, 0.05],
  [0.24, 0.05],
  [0.40, 0.065],
  [0.455, 0.115],
  [0.465, 0.20],
  [0.465, 1.26],
  [0.455, 1.285], // meniscus
  [0.42, 1.295],
  [0.001, 1.295],
]

export default function Bottle() {
  const glassGeo = useMemo(() => lathe(GLASS_PROFILE), [])
  const capGeo = useMemo(() => lathe(CAP_PROFILE), [])
  const liquidGeo = useMemo(() => lathe(LIQUID_PROFILE), [])

  return (
    <group>
      {/* Liquid must be OPAQUE: three's transmission pass renders only the
          opaque list into the refraction buffer, so a transparent liquid is
          invisible through the glass (and gets depth-rejected by the glass's
          own depth write in the main pass). Opaque rose + glossy finish reads
          as serum once the glass refracts it. Stars draw over it with
          depthTest off. */}
      <mesh geometry={liquidGeo} renderOrder={1}>
        <meshPhysicalMaterial
          color="#cc6f96"
          roughness={0.22}
          metalness={0}
          clearcoat={0.5}
          clearcoatRoughness={0.3}
          emissive="#b85f88"
          emissiveIntensity={0.28}
          envMapIntensity={0.5}
        />
      </mesh>

      {/* bright meniscus line on the liquid surface (opaque -> lands in the
          refraction buffer too, so the rim bends it) */}
      <mesh position={[0, 1.304, 0]} rotation={[-Math.PI / 2, 0, 0]} renderOrder={2}>
        <circleGeometry args={[0.415, 64]} />
        <meshBasicMaterial color={new THREE.Color(1.5, 1.12, 1.3)} toneMapped={false} />
      </mesh>

      {/* glass body */}
      <mesh geometry={glassGeo} renderOrder={3}>
        <meshPhysicalMaterial
          transmission={1}
          thickness={0.6}
          roughness={0.05}
          ior={1.45}
          attenuationColor="#f6d7de"
          attenuationDistance={2.5}
          clearcoat={1}
          clearcoatRoughness={0.06}
          color="#ffffff"
          envMapIntensity={0.7}
          specularIntensity={1}
        />
      </mesh>

      {/* gold dropper cap */}
      <mesh geometry={capGeo} renderOrder={4}>
        <meshStandardMaterial
          color="#e8dab6"
          metalness={1}
          roughness={0.2}
          envMapIntensity={1.3}
        />
      </mesh>
    </group>
  )
}
