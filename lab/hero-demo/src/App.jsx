import { useEffect, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { ContactShadows, Float } from '@react-three/drei'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import PearlBackdrop from './scene/PearlBackdrop.jsx'
import Wall from './scene/Wall.jsx'
import WindowFrame from './scene/WindowFrame.jsx'
import WindowLight from './scene/WindowLight.jsx'
import Bottle from './scene/Bottle.jsx'
import Stars from './scene/Stars.jsx'
import Particles from './scene/Particles.jsx'
import Table from './scene/Table.jsx'
import Mist from './scene/Mist.jsx'
import Rig from './scene/Rig.jsx'
import IngredientCard from './IngredientCard.jsx'
import { INGREDIENTS } from './ingredients.js'
import { INTRO_KEY } from './sequence.js'

function webglAvailable() {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

// resolves after the first real GL frame is rendered
function FirstFrame({ onDone }) {
  const fired = useRef(false)
  useFrame(() => {
    if (!fired.current) {
      fired.current = true
      onDone()
    }
  })
  return null
}

function StaticFallback() {
  return (
    <div className="hero">
      <div className="fallback-sky">
        <svg viewBox="0 0 300 360" width="300" height="360" aria-label="成分真言精华瓶">
          <rect x="60" y="90" width="180" height="240" rx="42" fill="#ffeef4" stroke="#8a5a6a" strokeWidth="4" />
          <rect x="72" y="180" width="156" height="138" rx="34" fill="#ff9ec2" />
          <rect x="72" y="180" width="156" height="26" rx="13" fill="#ffc9dd" />
          <rect x="104" y="52" width="92" height="58" rx="26" fill="#f5cf87" stroke="#8a5a6a" strokeWidth="4" />
          <circle cx="150" cy="46" r="12" fill="#f7d68f" stroke="#8a5a6a" strokeWidth="3" />
          <circle cx="120" cy="230" r="16" fill="#ffb347" />
          <circle cx="176" cy="252" r="12" fill="#7fd4ff" />
          <circle cx="150" cy="284" r="10" fill="#b18cff" />
          <circle cx="196" cy="216" r="9" fill="#ffd166" />
        </svg>
      </div>
      <HeroUi uiCls="ui-instant" card={null} onCloseCard={() => {}} />
    </div>
  )
}

function HeroUi({ uiCls, card, selectedIng, onCloseCard }) {
  return (
    <div className={`hero-ui ${uiCls}`}>
      <header className="topbar reveal d5">
        <div className="brand">成分真言</div>
        <div className="event">欧莱雅美妆科技黑客松 · 2026</div>
      </header>

      <main className="copy">
        <div className="eyebrow reveal d1">TRUTH IN INGREDIENTS</div>
        <h1 className="reveal d2">
          美，经得起
          <br />
          <span className="grad">逐滴核验</span>
        </h1>
        <p className="sub reveal d3">
          每一份配方浓度，皆有迹可循；
          <br />
          每一项功效宣称，皆有据可查。
        </p>
        <div className="ctas reveal d4">
          <a className="btn btn-primary" href="#library">
            浏览产品库 <span className="arrow">→</span>
          </a>
          <a className="btn btn-ghost" href="#evidence">
            查证成分证据
          </a>
        </div>
      </main>

      {card && <div className="card-veil" />}
      {card && selectedIng && (
        <IngredientCard ing={selectedIng} phase={card.phase} onClose={onCloseCard} />
      )}

      <div className="rail reveal d5">TRUTH · IN · INGREDIENTS — N°01</div>
    </div>
  )
}

export default function App() {
  const [glOk] = useState(webglAvailable)
  const [phase, setPhase] = useState('veil') // veil -> p1 -> p2 -> done; skip shortcut
  const [uiCls, setUiCls] = useState('')
  const [veilGone, setVeilGone] = useState(false)
  const [veilHidden, setVeilHidden] = useState(false)
  const [progress, setProgress] = useState(8)
  const [card, setCard] = useState(null) // { id, phase: 'enter' | 'exit' }
  const timers = useRef([])
  const cardTimer = useRef(null)

  // created once via lazy useState — a useRef(new Promise()) would re-run the
  // executor on every render and swap the resolver out from under the gate
  const [firstFrameReady] = useState(() => {
    let resolve
    const p = new Promise((r) => {
      resolve = r
    })
    return { p, resolve }
  })

  const selectedIng = card ? INGREDIENTS.find((i) => i.id === card.id) : null

  // debug/testing hooks (window.__orbScreen lives in Stars.jsx)
  useEffect(() => {
    window.__openCard = openCard
  })

  // ---- loading gate: fonts + first GL frame + min 600ms ------------------
  useEffect(() => {
    if (!glOk) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const played = sessionStorage.getItem(INTRO_KEY)
    let alive = true

    setProgress((p) => Math.max(p, 30))
    const fontsDone = document.fonts ? document.fonts.ready : Promise.resolve()
    fontsDone.then(() => alive && setProgress((p) => Math.max(p, 70)))
    firstFrameReady.p.then(() => alive && setProgress((p) => Math.max(p, 92)))

    Promise.all([fontsDone, firstFrameReady.p, new Promise((r) => setTimeout(r, 600))]).then(() => {
      if (!alive) return
      setProgress(100)
      setVeilGone(true)
      setTimeout(() => setVeilHidden(true), 480)
      if (played || reduced) {
        setPhase('done')
        setUiCls('ui-instant')
      } else {
        setPhase('p1')
      }
    })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [glOk])

  // ---- sequence bookkeeping ----------------------------------------------
  useEffect(() => {
    if (typeof window !== 'undefined') window.__introPhase = phase
  }, [phase])

  useEffect(() => {
    const clearTimers = () => {
      timers.current.forEach(clearTimeout)
      timers.current = []
    }

    if (phase === 'p1') {
      const skip = () => {
        setPhase('skip')
        setUiCls('ui-in ui-fast')
      }
      window.addEventListener('pointerdown', skip)
      window.addEventListener('keydown', skip)
      return () => {
        window.removeEventListener('pointerdown', skip)
        window.removeEventListener('keydown', skip)
      }
    }

    if (phase === 'p2') {
      setUiCls((c) => (c.includes('ui-fast') ? c : 'ui-in'))
      timers.current.push(setTimeout(() => setPhase('done'), 700))
      return clearTimers
    }

    if (phase === 'done') {
      sessionStorage.setItem(INTRO_KEY, '1')
      const forget = () => sessionStorage.removeItem(INTRO_KEY)
      window.addEventListener('beforeunload', forget)
      return () => window.removeEventListener('beforeunload', forget)
    }
  }, [phase])

  // ---- card open/close ----------------------------------------------------
  const openCard = (id) => {
    if (cardTimer.current) clearTimeout(cardTimer.current)
    setCard({ id, phase: 'enter' })
  }
  const closeCard = () => {
    setCard((c) => {
      if (!c || c.phase === 'exit') return c
      cardTimer.current = setTimeout(() => setCard(null), 380)
      return { ...c, phase: 'exit' }
    })
  }

  useEffect(() => {
    if (!card) return
    const onKey = (e) => {
      if (e.key === 'Escape') closeCard()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!card])

  if (!glOk) return <StaticFallback />

  return (
    <div className="hero">
      <Canvas
        dpr={[1, 1.75]}
        camera={{ fov: 33, position: [0, 5.5, 17], near: 0.1, far: 60 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        onPointerMissed={(e) => {
          if (e.type === 'click') closeCard()
        }}
      >
        <color attach="background" args={['#e8ddd2']} />
        <Wall />
        <WindowFrame />
        <WindowLight />
        <Mist />
        <Particles />
        <Table />

        <hemisphereLight args={['#fff0f5', '#e8d8cf', 0.7]} />
        {/* key light from the window direction: rose backlight + rim on the bottle */}
        <directionalLight position={[1.5, 3.2, -2.2]} intensity={1.15} color="#ffe0e6" />
        <directionalLight position={[-5, 2.5, -3]} intensity={0.55} color="#f0a8c4" />
        <directionalLight position={[-3, 1, 4]} intensity={0.32} color="#d8cce8" />
        <pointLight position={[0.7, 1.8, -2.6]} intensity={0.5} distance={9} color="#ffd9c9" />
        <pointLight position={[0, -1.5, 2.5]} intensity={0.25} color="#ffe6d6" />

        <Float speed={1.2} rotationIntensity={0.08} floatIntensity={0.15} floatingRange={[-0.02, 0.02]}>
          <Bottle />
          <Stars
            onSelect={openCard}
            selectedId={card?.id || null}
            interactive={phase === 'done'}
            appeared={phase === 'p2' || phase === 'skip' || phase === 'done'}
          />
        </Float>

        <ContactShadows
          position={[0.12, 0.001, 0]}
          scale={5.5}
          far={2.4}
          blur={2.8}
          opacity={0.26}
          resolution={512}
          color="#8a6a5e"
          frames={Infinity}
        />

        <Rig phase={phase} onPhase={setPhase} />
        <FirstFrame onDone={firstFrameReady.resolve} />

        <EffectComposer multisampling={4}>
          <Bloom mipmapBlur intensity={0.5} luminanceThreshold={0.8} luminanceSmoothing={0.15} radius={0.8} />
          <Vignette eskil={false} offset={0.28} darkness={0.14} />
        </EffectComposer>
      </Canvas>

      <HeroUi uiCls={uiCls} card={card} selectedIng={selectedIng} onCloseCard={closeCard} />

      {!veilHidden && (
        <div className={`p0-veil${veilGone ? ' hide' : ''}`}>
          <div className="p0-logo">成分真言</div>
          <div className="p0-track">
            <div className="p0-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}
    </div>
  )
}
