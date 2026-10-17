import { useEffect, useState } from 'react'
import { api } from '../api'
import { useResource } from './useResource'
import ProductPicker from './ProductPicker'
import CapabilityChart from './CapabilityChart'
import Contributions from './Contributions'
import SecondaryPanels from './SecondaryPanels'
import SimilarPicker from './SimilarPicker'
import EvidenceDrawer from './EvidenceDrawer'
import './showcase.css'

const CASES = [{ label: '黑绷带 / A.G.E.', a: 9, b: 73 }, { label: 'Serum 10 / C E Ferulic', a: 414, b: 3202 }]

export default function Showcase() {
  useEffect(() => {
    const previous = document.title
    document.title = '颜鉴｜护肤品功效证据对比'
    return () => { document.title = previous }
  }, [])
  const [pair, setPair] = useState({ a: 9, b: 73 })
  const [family, setFamily] = useState('保湿')
  const [source, setSource] = useState(null)
  const [similar, setSimilar] = useState(false)
  const a = useResource(() => api.product(pair.a), [pair.a])
  const b = useResource(() => api.product(pair.b), [pair.b])
  const aProfile = useResource(() => api.productCapabilityProfile(pair.a), [pair.a])
  const bProfile = useResource(() => api.productCapabilityProfile(pair.b), [pair.b])
  function select(side, id) {
    setPair(p => ({ ...p, [side]: id })); setSource(null); setSimilar(false)
  }
  function preset(example) {
    setPair({ a: example.a, b: example.b }); setFamily('保湿'); setSource(null); setSimilar(false)
  }
  return <main className="showcase-shell cap-shell">
    <header className="cap-intro"><div><p className="cap-wordmark">颜鉴 <span>每项指数，都能追到来源</span></p>
      <h1>护肤品功效证据对比</h1><p>选两款产品，看保湿、抗皱、修护等方向有哪些成分和证据支持。</p></div>
      <span className="cap-version">成分证据 · 浓度单列</span>
    </header>
    <nav className="cap-presets" aria-label="真实演示案例"><span>演示案例</span>{CASES.map(c => <button type="button" key={c.a} aria-pressed={pair.a === c.a && pair.b === c.b} onClick={() => preset(c)}>{c.label}</button>)}</nav>
    <div className="cap-products">
      <ProductPicker side="A" productId={pair.a} state={a} onSelect={id => select('a', id)} />
      <ProductPicker side="B" productId={pair.b} state={b} onSelect={id => select('b', id)} onSimilar={() => setSimilar(true)} />
    </div>
    <div className="cap-main-grid">
      <CapabilityChart a={aProfile} b={bProfile} aId={pair.a} bId={pair.b} family={family} onFamily={setFamily} />
      <Contributions a={aProfile} b={bProfile} family={family} onSource={setSource} />
    </div>
    {a.data && b.data && <SecondaryPanels key={`${pair.a}-${pair.b}`} a={a.data} b={b.data} onIngredient={setSource} />}
    {similar && <SimilarPicker key={pair.a} targetId={pair.a} onClose={() => setSimilar(false)} onSelect={id => select('b', id)} />}
    {source && <EvidenceDrawer key={`${source.ingredientId}-${source.contribution?.assertion_id || ''}-${source.side || ''}`} ingredientId={source.ingredientId} context={source} onClose={() => setSource(null)} />}
    <footer className="cap-footer">成分相似不代表功效等同。指数是已收录资料的参考汇总，不是成品实测效果、有效率或综合质量评分。<br />不能确定时，明确说不能确定。</footer>
  </main>
}
