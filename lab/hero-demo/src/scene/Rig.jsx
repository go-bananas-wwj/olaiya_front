import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

const BASE_POS = new THREE.Vector3(0, 1.4, 6.05)
const BASE_LOOK = new THREE.Vector3(-0.55, 1.18, 0)

// Gentle mouse parallax: damped drift around the base pose.
export default function Rig() {
  useFrame((state, dt) => {
    const { camera, pointer } = state
    const k = 2.2
    camera.position.x = THREE.MathUtils.damp(camera.position.x, BASE_POS.x + pointer.x * 0.38, k, dt)
    camera.position.y = THREE.MathUtils.damp(camera.position.y, BASE_POS.y + pointer.y * 0.22, k, dt)
    camera.position.z = THREE.MathUtils.damp(camera.position.z, BASE_POS.z, k, dt)
    camera.lookAt(BASE_LOOK.x + pointer.x * 0.1, BASE_LOOK.y + pointer.y * 0.06, BASE_LOOK.z)
  })
  return null
}
