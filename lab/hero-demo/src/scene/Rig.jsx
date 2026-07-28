import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { easeInOut } from '../sequence.js'

// Camera choreography.
//   veil : hold the far tableau pose (table + sky visible)
//   p1   : dolly (0,5.5,17) -> hero pose over 3.4s, cubic-bezier(0.65,0,0.35,1);
//          the look target lingers on the scene for the first 30%, then
//          converges on the bottle (doc: front 40% scene / back 60% bottle)
//   skip : 300ms fast-forward from wherever we are to the hero pose
//   p2/done : gentle mouse parallax around the hero pose
//
// NOTE on the final pose: the doc lists (0,1.7,7.2) as the hero camera, but
// its own acceptance criteria requires the end frame to match the approved
// hero composition, which is (0,1.4,6.05) looking at (-0.55,1.18,0). The
// approved framing wins; the deviation is recorded in the lab report.

const FAR_POS = new THREE.Vector3(0, 5.5, 17)
const FAR_LOOK = new THREE.Vector3(0, 1.9, -1)
const HERO_POS = new THREE.Vector3(0, 1.4, 6.05)
const HERO_LOOK = new THREE.Vector3(-0.1, 1.18, 0)
const P1_S = (() => {
  const q = new URLSearchParams(window.location.search).get('p1')
  const v = q ? parseFloat(q) : NaN
  return Number.isFinite(v) && v > 0 ? v : 3.4
})() // ?p1=12 slows the dolly for trajectory screenshots
const SKIP_S = 0.3

export default function Rig({ phase, onPhase }) {
  const start = useRef(null)
  const skipStart = useRef(null)
  const fromPos = useRef(new THREE.Vector3())
  const fromLook = useRef(new THREE.Vector3())
  const lookCur = useRef(FAR_LOOK.clone())
  const pos = useMemo(() => new THREE.Vector3(), [])
  const look = useMemo(() => new THREE.Vector3(), [])

  useFrame((state, dt) => {
    const { camera, pointer, clock } = state
    const t = clock.elapsedTime
    if (typeof window !== 'undefined') {
      window.__camProbe = [
        phase,
        Number(camera.position.x.toFixed(2)),
        Number(camera.position.y.toFixed(2)),
        Number(camera.position.z.toFixed(2)),
      ]
    }

    if (phase === 'veil') {
      camera.position.copy(FAR_POS)
      lookCur.current.copy(FAR_LOOK)
      camera.lookAt(FAR_LOOK)
      return
    }

    if (phase === 'p1') {
      if (start.current === null) start.current = t
      const raw = Math.min(1, (t - start.current) / P1_S)
      const e = easeInOut(raw)
      pos.lerpVectors(FAR_POS, HERO_POS, e)
      const lookT = easeInOut(THREE.MathUtils.clamp((raw - 0.3) / 0.7, 0, 1))
      look.lerpVectors(FAR_LOOK, HERO_LOOK, lookT)
      camera.position.copy(pos)
      lookCur.current.copy(look)
      camera.lookAt(look)
      if (raw >= 1) onPhase('p2')
      return
    }

    if (phase === 'skip') {
      if (skipStart.current === null) {
        skipStart.current = t
        fromPos.current.copy(camera.position)
        fromLook.current.copy(lookCur.current)
      }
      const raw = Math.min(1, (t - skipStart.current) / SKIP_S)
      const e = easeInOut(raw)
      pos.lerpVectors(fromPos.current, HERO_POS, e)
      look.lerpVectors(fromLook.current, HERO_LOOK, e)
      camera.position.copy(pos)
      lookCur.current.copy(look)
      camera.lookAt(look)
      if (raw >= 1) onPhase('done')
      return
    }

    // p2 / done: damped mouse parallax around the hero pose
    const k = 2.2
    camera.position.x = THREE.MathUtils.damp(camera.position.x, HERO_POS.x + pointer.x * 0.38, k, dt)
    camera.position.y = THREE.MathUtils.damp(camera.position.y, HERO_POS.y + pointer.y * 0.22, k, dt)
    camera.position.z = THREE.MathUtils.damp(camera.position.z, HERO_POS.z, k, dt)
    lookCur.current.x = THREE.MathUtils.damp(lookCur.current.x, HERO_LOOK.x + pointer.x * 0.1, k, dt)
    lookCur.current.y = THREE.MathUtils.damp(lookCur.current.y, HERO_LOOK.y + pointer.y * 0.06, k, dt)
    lookCur.current.z = HERO_LOOK.z
    camera.lookAt(lookCur.current)
  })
  return null
}
