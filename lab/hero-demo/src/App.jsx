import { Canvas } from '@react-three/fiber'
import { ContactShadows, Environment, Float, Lightformer } from '@react-three/drei'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import PearlBackdrop from './scene/PearlBackdrop.jsx'
import Bottle from './scene/Bottle.jsx'
import Stars from './scene/Stars.jsx'
import Rig from './scene/Rig.jsx'

export default function App() {
  return (
    <div className="hero">
      <Canvas
        dpr={[1, 1.75]}
        camera={{ fov: 33, position: [0, 1.32, 6.15], near: 0.1, far: 60 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#f3ede6']} />
        <PearlBackdrop />

        <ambientLight intensity={0.22} color="#fff4ec" />
        <directionalLight position={[4, 6, 4]} intensity={0.8} color="#fff2e8" />
        <directionalLight position={[-5, 2.5, -3]} intensity={0.7} color="#e8a4c0" />
        <directionalLight position={[-3, 1, 4]} intensity={0.32} color="#b9aee0" />
        <pointLight position={[0, -1.5, 2.5]} intensity={0.3} color="#ffe6d6" />

        <Environment resolution={256}>
          {/* tall strips at the sides -> rim streaks that trace the silhouette */}
          <Lightformer form="rect" intensity={1.3} position={[0, 5.5, -3]} scale={[7, 3.5, 1]} color="#fff5ee" />
          <Lightformer form="rect" intensity={1.7} position={[-5.2, 1.8, 0.8]} scale={[1.2, 6.5, 1]} color="#f3c3d4" />
          <Lightformer form="rect" intensity={1.5} position={[5.4, 1.6, 0.6]} scale={[1.1, 6, 1]} color="#d3e6df" />
          <Lightformer form="rect" intensity={1.7} position={[0, 4.2, -5]} scale={[5, 1.4, 1]} color="#ffffff" />
          <Lightformer form="rect" intensity={2.4} position={[2.2, 2.6, 3.2]} scale={[2.2, 1.3, 1]} color="#f0d5a0" />
          <Lightformer form="rect" intensity={2.6} position={[0.5, 2.5, 5.5]} scale={[3.5, 1.0, 1]} color="#f7e7c4" />
          <Lightformer form="circle" intensity={0.8} position={[0, 1.5, 6]} scale={2.6} color="#fff9f2" />
          <Lightformer form="rect" intensity={0.9} position={[0, -4, 1]} rotation-x={Math.PI / 2} scale={[5, 5, 1]} color="#e6d9f0" />
        </Environment>

        <group position={[0, 0.1, 0]}>
          <Float speed={1.4} rotationIntensity={0.12} floatIntensity={0.55} floatingRange={[-0.06, 0.06]}>
            <Bottle />
            <Stars />
          </Float>
        </group>

        <ContactShadows
          position={[0.12, 0.001, 0]}
          scale={5.5}
          far={2.4}
          blur={2.8}
          opacity={0.32}
          resolution={512}
          color="#7d5450"
          frames={Infinity}
        />

        <Rig />

        <EffectComposer multisampling={4}>
          <Bloom mipmapBlur intensity={0.55} luminanceThreshold={0.85} luminanceSmoothing={0.12} radius={0.65} />
          <Vignette eskil={false} offset={0.28} darkness={0.16} />
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

        <div className="rail">TRUTH · IN · INGREDIENTS — N°01</div>
      </div>
    </div>
  )
}
