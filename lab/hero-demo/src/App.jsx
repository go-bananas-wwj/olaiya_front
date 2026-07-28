import { useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { ContactShadows, Float } from '@react-three/drei'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import PearlBackdrop from './scene/PearlBackdrop.jsx'
import Bottle from './scene/Bottle.jsx'
import Stars from './scene/Stars.jsx'
import Particles from './scene/Particles.jsx'
import Rig from './scene/Rig.jsx'
import IngredientCard from './IngredientCard.jsx'
import { INGREDIENTS } from './ingredients.js'

export default function App() {
  const [selectedId, setSelectedId] = useState(null)
  const selected = INGREDIENTS.find((i) => i.id === selectedId) || null

  return (
    <div className="hero">
      <Canvas
        dpr={[1, 1.75]}
        camera={{ fov: 33, position: [0, 1.4, 6.05], near: 0.1, far: 60 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        onPointerMissed={(e) => {
          if (e.type === 'click') setSelectedId(null)
        }}
      >
        <color attach="background" args={['#f3ede6']} />
        <PearlBackdrop />
        <Particles />

        <hemisphereLight args={['#fff0f5', '#e8d8cf', 0.85]} />
        <directionalLight position={[4, 6, 4]} intensity={1.0} color="#fff2e8" />
        <directionalLight position={[-5, 2.5, -3]} intensity={0.55} color="#f0a8c4" />
        <directionalLight position={[-3, 1, 4]} intensity={0.3} color="#c9bce8" />
        <pointLight position={[0, -1.5, 2.5]} intensity={0.25} color="#ffe6d6" />

        <group position={[0, 0.1, 0]}>
          <Float speed={1.4} rotationIntensity={0.12} floatIntensity={0.55} floatingRange={[-0.06, 0.06]}>
            <Bottle />
            <Stars onSelect={setSelectedId} selectedId={selectedId} />
          </Float>
        </group>

        <ContactShadows
          position={[0.12, 0.001, 0]}
          scale={5.5}
          far={2.4}
          blur={2.8}
          opacity={0.24}
          resolution={512}
          color="#a06a78"
          frames={Infinity}
        />

        <Rig />

        <EffectComposer multisampling={4}>
          <Bloom mipmapBlur intensity={0.5} luminanceThreshold={0.8} luminanceSmoothing={0.15} radius={0.8} />
          <Vignette eskil={false} offset={0.28} darkness={0.14} />
        </EffectComposer>
      </Canvas>

      <div className="hero-ui">
        <header className="topbar">
          <div className="brand">成分真言</div>
          <div className="event">欧莱雅美妆科技黑客松 · 2026</div>
        </header>

        <main className="copy">
          <div className="eyebrow">TRUTH IN INGREDIENTS</div>
          <h1>
            美，经得起
            <br />
            <span className="grad">逐滴核验</span>
          </h1>
          <p className="sub">
            每一份配方浓度，皆有迹可循；
            <br />
            每一项功效宣称，皆有据可查。
          </p>
          <div className="ctas">
            <a className="btn btn-primary" href="#library">
              浏览产品库 <span className="arrow">→</span>
            </a>
            <a className="btn btn-ghost" href="#evidence">
              查证成分证据
            </a>
          </div>
        </main>

        <IngredientCard ing={selected} onClose={() => setSelectedId(null)} />

        <div className="rail">TRUTH · IN · INGREDIENTS — N°01</div>
      </div>
    </div>
  )
}
