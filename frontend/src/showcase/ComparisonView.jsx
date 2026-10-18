import { useEffect, useRef, useState } from 'react'
import { ArrowRight, ArrowLeft, Check, Minus, Flask } from '@phosphor-icons/react'
import { api } from '../api'
import { useResource } from './useResource'
import ProductPicker from './ProductPicker'
import CapabilityChart from './CapabilityChart'
import Contributions from './Contributions'
import SecondaryPanels from './SecondaryPanels'
import SimilarPicker from './SimilarPicker'
import EvidenceDrawer from './EvidenceDrawer'
import { ProductPhoto, SectionHeading, productPhotos } from './ReferencePrimitives'
import './showcase.css'

const CASES = [{ label: '黑绷带 / A.G.E.', a: 9, b: 73 }, { label: 'Serum 10 / C E Ferulic', a: 414, b: 3202 }]
const SECTIONS = [['overview','产品概览'],['benefits','功效证据'],['key-ingredients','贡献成分'],['ingredients','成分对照'],['price','参考价格'],['explained','成分解释'],['alternatives','相似候选']]
const catalogProduct = id => ({ id, ...productPhotos[String(id)], source_url: productPhotos[String(id)]?.source_page })

function OverviewFacts({ product, profile, side }) {
  const p = product.data, data = profile.data
  const contributors = [...new Map((data?.dimensions || []).flatMap(d => d.contributions).map(c => [c.ingredient_id, c])).values()]
  const withConcentration = contributors.filter(c => c.concentration.status !== 'unknown').length
  const facts = [
    ['成分表已收录', p ? `${p.ingredients.length} 项` : '未加载', p ? p.ingredients.length > 0 : null],
    ['可计入功效指数的成分', data ? `${data.coverage.ingredients_scored} 项` : '未加载', data ? data.coverage.ingredients_scored > 0 : null],
    ['计分成分中的浓度资料', data ? `${withConcentration} / ${contributors.length} 项` : '未加载', data ? withConcentration > 0 : null],
  ]
  return <div className="ss-overview-facts" aria-label={`产品 ${side} 已收录资料`}>
    {facts.map(([label, value, available]) => <div key={label}><span>{label}<small>{value}</small></span>
      <span className={available ? 'ss-fact-available' : 'ss-fact-unknown'} aria-label={available ? '有该项资料' : '暂无可确认资料'}>{available ? <Check size={13} weight="bold" /> : <Minus size={13} />}</span>
    </div>)}
  </div>
}

export default function ComparisonView({ initialPair = { a: 9, b: 73 }, onBack }) {
  const [pair, setPair] = useState(initialPair)
  const [family, setFamily] = useState('保湿')
  const [source, setSource] = useState(null)
  const [similar, setSimilar] = useState(null)
  const [active, setActive] = useState('overview')
  const [sticky, setSticky] = useState(false)
  const overview = useRef(null)
  const a = useResource(() => api.product(pair.a), [pair.a])
  const b = useResource(() => api.product(pair.b), [pair.b])
  const aProfile = useResource(() => api.productCapabilityProfile(pair.a), [pair.a])
  const bProfile = useResource(() => api.productCapabilityProfile(pair.b), [pair.b])
  useEffect(() => {
    const previous = document.title
    document.title = '颜鉴｜护肤品功效证据对比'
    document.body.classList.add('reference-compare')
    return () => { document.title = previous; document.body.classList.remove('reference-compare') }
  }, [])
  useEffect(() => {
    function update() {
      setSticky(Boolean(overview.current && overview.current.getBoundingClientRect().bottom < 70))
      let current = 'overview'
      for (const [id] of SECTIONS) {
        if (document.getElementById(id)?.getBoundingClientRect().top <= 150) current = id
      }
      setActive(current)
    }
    update(); window.addEventListener('scroll', update, { passive: true })
    return () => window.removeEventListener('scroll', update)
  }, [pair.a, pair.b])
  function select(side, id) { setPair(p => ({ ...p, [side]: id })); setSource(null); setSimilar(null) }
  function preset(example) {
    setPair({ a: example.a, b: example.b }); setFamily('保湿'); setSource(null); setSimilar(null)
    window.scrollTo({ top: 0, behavior: 'instant' })
  }
  function showFamily(value) {
    setFamily(value)
    document.getElementById('key-ingredients')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  return <main className="ss-app">
    <header className="ss-masthead">{onBack && <button type="button" className="ss-return-map" onClick={onBack}><ArrowLeft size={14}/>返回产品地图</button>}<a href="#overview" className="ss-wordmark"><Flask size={22} weight="duotone" />颜鉴</a><h1>护肤品功效证据对比</h1><a href="#method">每项指数，都能追到来源</a></header>
    <div className="ss-page">
      <div className="ss-breadcrumb"><span>产品对比</span><span>/</span><strong>{a.data?.brand || '产品 A'} {a.data?.name || ''} VS {b.data?.brand || '产品 B'} {b.data?.name || ''}</strong></div>
      <div className="ss-layout">
        <div className="ss-content">
          <nav className="ss-presets" aria-label="真实演示案例"><span>演示案例</span>{CASES.map(c => <button type="button" key={c.a} aria-pressed={pair.a === c.a && pair.b === c.b} onClick={() => preset(c)}>{c.label}</button>)}</nav>
          <section id="overview" ref={overview} className="ss-overview" aria-label="产品概览">
            <div className="ss-products ss-two-columns"><ProductPicker side="A" productId={pair.a} state={a} onSelect={id => select('a', id)} />
              <ProductPicker side="B" productId={pair.b} state={b} onSelect={id => select('b', id)} />
              <span className="ss-versus">Versus</span>
            </div>
            <div className="ss-two-columns ss-product-description">{[[a, aProfile], [b, bProfile]].map(([state, profile], i) => <p key={i}>{state.data ? <>本库收录 <strong>{state.data.ingredients.length} 项成分</strong>。{profile.data ? <><strong>{profile.data.coverage.ingredients_scored} 个成分</strong>有资料可计入功效证据指数。</> : '证据资料正在独立读取。'}点击功效方向可查看依据。</> : '产品资料尚未就绪。'}</p>)}</div>
            <div className="ss-two-columns ss-category-row"><p>{a.data?.category || '类别未收录'}</p><p>{b.data?.category || '类别未收录'}</p></div>
            <div className="ss-two-columns ss-facts-columns"><OverviewFacts product={a} profile={aProfile} side="A" /><OverviewFacts product={b} profile={bProfile} side="B" /></div>
            <p className="ss-section-note">以上勾选仅表示资料已收录，不是安全认证或成品功效结论。参考图用于识别产品，不据图片推断现售包装、版本或规格。</p>
          </section>
          <CapabilityChart a={aProfile} b={bProfile} aId={pair.a} bId={pair.b} productA={a.data} productB={b.data} family={family} onFamily={showFamily} />
          <section id="key-ingredients" className="ss-block"><SectionHeading title="贡献成分" a={a.data} b={b.data} /><Contributions a={aProfile} b={bProfile} family={family} onSource={setSource} /></section>
          <SecondaryPanels key={`${pair.a}-${pair.b}`} a={a.data} b={b.data} onIngredient={setSource} />
          <section id="alternatives" className="ss-block"><SectionHeading title="相似候选" a={a.data} b={b.data} />
            <div className="ss-two-columns ss-alternatives">{[[a, 'A', 'b'], [b, 'B', 'a']].map(([state, side, replace]) => <button type="button" key={side}
              aria-label={side === 'A' ? '找相似产品' : '查找与产品 B 相似的候选'} disabled={!state.data} onClick={() => setSimilar({ targetId: state.data.id, side, replace })}>
              <strong>寻找产品 {side} 的相似候选</strong><span>查看成分接近的产品，替换另一款进行对照。</span><span>查看候选 <ArrowRight size={13} /></span>
            </button>)}</div>
          </section>
          <section className="ss-block ss-more-comparisons" aria-label="更多真实对比"><h2>更多真实对比</h2><div className="ss-comparison-cards">{CASES.map(c => <button type="button" key={c.a} onClick={() => preset(c)}>
            <span className="ss-two-columns">{[c.a, c.b].map(id => { const p = catalogProduct(id); return <span key={id}><span className="ss-card-photo"><ProductPhoto product={p} side="" /></span><small>{p.brand}</small><strong>{p.name}</strong></span> })}</span>
            <span className="ss-comparison-cta">查看这组对比 <ArrowRight size={12} /></span>
          </button>)}</div></section>
        </div>
        <nav className={`ss-directory ${sticky ? 'has-sticky' : ''}`} aria-label="页面目录"><p>本页目录</p>{SECTIONS.map(([id, title]) => <a key={id} href={`#${id}`} aria-current={active === id ? 'location' : undefined}>{title}</a>)}</nav>
      </div>
      <footer className="ss-footer">成分相似不代表功效等同。证据指数是已收录资料的参考汇总，不是成品实测效果、有效率或综合质量评分。<br />功能分类、安全与法规不是功效实证；不能确定时，明确说不能确定。</footer>
    </div>
    <div className="ss-sticky-products" data-testid="comparison-sticky" hidden={!sticky}><div className="ss-two-columns">{[[a.data, 'A'], [b.data, 'B']].map(([p, side]) => <a href="#overview" key={side}><ProductPhoto product={p} side={side} mini /><span>产品 {side} · {p?.brand}<strong>{p?.name || `产品 ${side}`}</strong></span></a>)}</div></div>
    {similar && <SimilarPicker key={similar.targetId} targetId={similar.targetId} referenceLabel={similar.side} onClose={() => setSimilar(null)} onSelect={id => select(similar.replace, id)} />}
    {source && <EvidenceDrawer key={`${source.ingredientId}-${source.contribution?.assertion_id || ''}-${source.side || ''}`} ingredientId={source.ingredientId} context={source} onClose={() => setSource(null)} />}
  </main>
}
