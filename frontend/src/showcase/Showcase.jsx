import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import PriceInfo from '../components/PriceInfo'
import EvidenceSummary from '../components/EvidenceSummary'
import EvidenceDrawer from './EvidenceDrawer'
import RoundtablePanel from './RoundtablePanel'
import { compareIngredients, sortCandidates } from './logic.mjs'
import './showcase.css'

const CASES = [{ label: '黑绷带 / A.G.E.', target: 9, candidate: 73 }, { label: 'Serum 10 / C E Ferulic', target: 414, candidate: 3202 }]
const nameOf = i => i.cn_name || i.inci_name

function useResource(load, deps) {
  const identity = JSON.stringify(deps)
  const [state, setState] = useState({ loading: true, identity })
  useEffect(() => {
    let current = true
    setState({ loading: true, identity })
    Promise.resolve().then(load).then(data => { if (current) setState({ data, identity }) })
      .catch(error => { if (current) setState({ error: error.message, identity }) })
    return () => { current = false }
  }, deps) // Each call explicitly supplies its resource identity.
  return state.identity === identity ? state : { loading: true }
}

function IngredientButtons({ items, onIngredient, testId }) {
  return <div className="flex flex-wrap gap-2 mt-3" data-testid={testId}>
    {!items.length && <p className="text-xs text-pearl-ink-3">无列出成分</p>}
    {items.map(i => <button type="button" className="fairy-chip text-left break-words" key={i.ingredient_id} onClick={() => onIngredient(i.ingredient_id)}>{nameOf(i)}</button>)}
  </div>
}

function ProductCard({ product, label, onIngredient, testId }) {
  const evidence = useResource(() => api.productEvidenceProfile(product.id), [product.id])
  const ordered = [...product.ingredients].sort((a, b) => (a.position ?? Infinity) - (b.position ?? Infinity))
  return <article className="fairy-panel p-5 min-w-0" data-testid={testId}>
    <p className="text-xs text-iris mb-3">{label}</p>
    <p className="text-sm text-pearl-ink-2">{product.brand}</p>
    <h3 className="font-semibold text-lg leading-snug mt-1 break-words">{product.name}</h3>
    <div className="mt-4"><PriceInfo product={product} /></div>
    <details className="text-xs mt-4"><summary>产品与成分来源</summary>
      {product.source_url ? <a href={product.source_url} target="_blank" rel="noreferrer" className="block text-iris underline mt-2 break-all">原始来源 ↗</a> : <p className="mt-2">来源链接未记录</p>}
      {product.note && <p className="mt-2 whitespace-pre-wrap">{product.note}</p>}
    </details>
    <details className="mt-4 text-sm"><summary>完整成分表（{ordered.length} 项）</summary>
      <p className="text-xs text-pearl-ink-3 mt-3">位次未知时不推测顺序或浓度。点击成分查看资料。</p>
      <ol className="mt-2 space-y-2">{ordered.map(i => <li key={i.ingredient_id} className="flex gap-2 items-start text-xs">
        <span className="text-pearl-ink-3 min-w-12 pt-1">{i.position == null ? '未知位次' : `#${i.position}`}</span>
        <button className="text-iris text-left underline break-words py-1" onClick={() => onIngredient(i.ingredient_id)}>{nameOf(i)}</button>
      </li>)}</ol>
    </details>
    <details className="mt-4 text-sm"><summary>证据覆盖与局限</summary><div className="mt-3"><EvidenceSummary state={evidence} /></div></details>
  </article>
}

function Comparison({ target, candidate, onIngredient }) {
  const difference = compareIngredients(target.ingredients, candidate.ingredients)
  const comparable = target.unit_price != null && candidate.unit_price != null && target.unit_price_unit === candidate.unit_price_unit
  return <section className="glass-card">
    <h2 className="pearl-title">共有与差异成分</h2>
    <div className="grid md:grid-cols-2 gap-4">
      <ProductCard key={`a-${target.id}`} product={target} label="参照产品" testId="target-product" onIngredient={onIngredient} />
      <ProductCard key={`b-${candidate.id}`} product={candidate} label="对照产品" testId="candidate-product" onIngredient={onIngredient} />
    </div>
    {!comparable && <p className="text-xs text-pearl-ink-3 mt-4">价格或可比规格不足，不计算单价差异；ml 与 g 不互换。</p>}
    <div className="mt-6"><h3 className="text-sm font-semibold">共有成分 · {difference.shared.length}</h3><IngredientButtons testId="shared-ingredients" items={difference.shared} onIngredient={onIngredient} /></div>
    <div className="grid md:grid-cols-2 gap-5 mt-5">
      <div><h3 className="text-sm font-semibold">仅参照产品列出 · {difference.onlyTarget.length}</h3><IngredientButtons items={difference.onlyTarget} onIngredient={onIngredient} /></div>
      <div><h3 className="text-sm font-semibold">仅对照产品列出 · {difference.onlyCandidate.length}</h3><IngredientButtons items={difference.onlyCandidate} onIngredient={onIngredient} /></div>
    </div>
  </section>
}

function Workspace({ targetId, initialCandidate, onIngredient }) {
  const [method, setMethod] = useState('overlap')
  const [sort, setSort] = useState('similarity')
  const [candidateId, setCandidateId] = useState(initialCandidate)
  const targetState = useResource(() => api.product(targetId), [targetId])
  const similar = useResource(() => method === 'overlap'
    ? api.productSimilarLevels(targetId, { k: 12 }).then(r => ({ items: r.l1 }))
    : api.productSimilar(targetId, { k: 12 }).then(r => ({ items: r.similar || [], reason: r.reason })), [targetId, method])
  const target = targetState.data
  const items = useMemo(() => sortCandidates(similar.data?.items || [], sort, target?.unit_price_unit), [similar.data, sort, target?.unit_price_unit])
  const effectiveCandidate = candidateId || items[0]?.id
  const candidate = useResource(() => effectiveCandidate ? api.product(effectiveCandidate) : null, [effectiveCandidate])

  if (targetState.loading) return <p className="glass-card" role="status">正在读取产品与成分…</p>
  if (targetState.error) return <p className="glass-card" role="alert">产品加载失败：{targetState.error}</p>
  return <>
    <section className="glass-card">
      <div className="showcase-section-head"><div><h2 className="pearl-title">寻找相似构成</h2><p className="text-sm text-pearl-ink-2 break-words">参照：{target.brand} · {target.name}</p></div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="相似检索方式">{[['overlap', '成分重合'], ['embedding', '嵌入相似']].map(([value, label]) => <button className={method === value ? 'btn-fairy' : 'btn-fairy-ghost'} aria-pressed={method === value} key={value} onClick={() => setMethod(value)}>{label}</button>)}</div>
      </div>
      <div className="flex flex-wrap items-center gap-3 mt-5 text-xs">
        <label>候选排序 <select aria-label="候选排序" className="input ml-2 !w-auto !py-1" value={sort} onChange={e => setSort(e.target.value)}><option value="similarity">按相似度</option><option value="price" disabled={!target.unit_price_unit}>同单位单价优先</option></select></label>
        <span className="text-pearl-ink-3">仅排序本次候选，缺价或不同单位排后。</span>
      </div>
      <p className="text-xs text-pearl-ink-3 mt-3">{method === 'overlap' ? '成分重合为集合 Jaccard；不考虑浓度。' : '嵌入分数为成分表向量的余弦相似度。'} 相似不代表功效等同。</p>
      {similar.loading && <p role="status" className="mt-4 text-sm">正在查找候选…</p>}
      {similar.error && <p role="alert" className="pearl-notice mt-4">候选加载失败：{similar.error}</p>}
      {similar.data?.reason && <p className="pearl-notice mt-4">{similar.data.reason}，可切换成分重合继续对照。</p>}
      {similar.data && !items.length && !similar.data.reason && <p className="mt-4 text-sm">暂未找到可展示的候选。</p>}
      <div className="showcase-candidates mt-4">{items.map(item => <button key={item.id} className={`showcase-candidate ${effectiveCandidate === item.id ? 'is-selected' : ''}`} aria-pressed={effectiveCandidate === item.id} onClick={() => setCandidateId(item.id)}>
        <span className="text-xs text-iris">{item.brand}</span><span className="block text-sm font-semibold mt-2 break-words">{item.name}</span>
        <span className="block text-xs text-pearl-ink-2 mt-3">{method === 'overlap' ? `成分重合 ${(item.score * 100).toFixed(1)}%` : `余弦相似 ${item.score.toFixed(3)}`} · 共有 {item.shared} 项</span>
        <span className="block text-xs mt-2">{item.price_current == null ? '暂无价格' : `参考价 ¥${item.price_current}`}{item.spec ? ` / ${item.spec}` : ''}</span>
      </button>)}</div>
      {initialCandidate && !items.some(i => i.id === initialCandidate) && !similar.loading && <p className="text-xs text-pearl-ink-3 mt-3">精选案例为独立对照，可能不在当前前 12 个相似候选中。</p>}
    </section>
    {candidate.loading && effectiveCandidate && <p className="glass-card" role="status">正在读取对照产品…</p>}
    {candidate.error && <p className="glass-card" role="alert">对照产品加载失败：{candidate.error}</p>}
    {candidate.data ? <Comparison target={target} candidate={candidate.data} onIngredient={onIngredient} />
      : !candidate.loading && <section className="glass-card"><ProductCard product={target} label="参照产品" testId="target-product" onIngredient={onIngredient} /></section>}
    <RoundtablePanel key={`${target.id}-${candidate.data?.id || ''}`} target={target} candidate={candidate.data} />
  </>
}

export default function Showcase() {
  const [selection, setSelection] = useState({ ...CASES[0], version: 0 })
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState({ items: [] })
  const [ingredientId, setIngredientId] = useState(null)
  useEffect(() => {
    let current = true
    setSearch({ items: [], loading: Boolean(query.trim()) })
    const timer = setTimeout(() => {
      if (!query.trim()) return
      api.products({ q: query.trim(), limit: 8 }).then(r => { if (current) setSearch({ items: r.items || r }) })
        .catch(error => { if (current) setSearch({ items: [], error: error.message }) })
    }, 220)
    return () => { current = false; clearTimeout(timer) }
  }, [query])
  function select(target, candidate = null) {
    setSelection(previous => ({ target, candidate, version: previous.version + 1 }))
    setIngredientId(null)
    setQuery('')
  }
  return <main className="showcase-shell">
    <header className="showcase-header"><a href="#" className="font-display text-xl text-iris">颜鉴</a><span className="pearl-badge-muted">有据可查 · 未知不猜</span></header>
    <section className="showcase-intro">
      <p className="text-sm text-iris tracking-wider">看构成，找相似，再看证据</p>
      <h1 className="font-display text-4xl md:text-5xl mt-3 grad-text">成分对照台</h1>
      <p className="text-sm md:text-base text-pearl-ink-2 mt-4">贵在哪里，像在哪里？把成分、参考价格和证据放在一起看。</p>
    </section>
    <section className="glass-card">
      <label htmlFor="showcase-search" className="block text-sm font-semibold mb-3">选择你的参照产品</label>
      <input id="showcase-search" aria-label="搜索参照产品" className="input" value={query} onChange={e => setQuery(e.target.value)} placeholder="输入品牌或产品名，如烟酰胺、修丽可" autoComplete="off" />
      {query.trim() && <div className="mt-3" aria-live="polite">
        {search.loading && <p className="text-sm">搜索中…</p>}
        {search.error && <p className="text-sm" role="alert">搜索失败：{search.error}</p>}
        {!search.loading && !search.error && !search.items.length && <p className="text-sm">未找到产品，请换一个关键词。</p>}
        {search.items.map(p => <button key={p.id} className="showcase-search-result" aria-label={`选择 ${p.name}`} onClick={() => select(p.id)}><span className="text-xs text-iris">{p.brand}</span><span className="block text-sm mt-1">{p.name}</span></button>)}
      </div>}
      <div className="flex flex-wrap items-center gap-2 mt-4"><span className="text-xs text-pearl-ink-3">试试真实案例</span>{CASES.map(c => <button key={c.target} className="btn-page" onClick={() => select(c.target, c.candidate)}>{c.label}</button>)}</div>
    </section>
    <Workspace key={selection.version} targetId={selection.target} initialCandidate={selection.candidate} onIngredient={setIngredientId} />
    {ingredientId && <EvidenceDrawer key={ingredientId} ingredientId={ingredientId} onClose={() => setIngredientId(null)} />}
    <footer className="text-xs text-pearl-ink-3 text-center pb-6 leading-relaxed">参考价格为历史采样，非实时售价。成分相似不代表功效等同。<br />每个结论都能追到来源；不能确定时明确说不能确定。</footer>
  </main>
}
