import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from '../components/common'
import PriceInfo from '../components/PriceInfo'
import EvidenceSummary from '../components/EvidenceSummary'

// 预设对比组（2026-08-15 查库确认的真实 id）：
// 2 = The Ordinary 烟酰胺10%+锌1%精华；3202 = 修丽可 C E Ferulic 15% 精华
// （511/2821 同名 CE 产品无官方降序成分表、无成本数据，故选 3202）
const PRESETS = [
  { label: 'The Ordinary 烟酰胺 vs 修丽可 CE', a: 2, b: 3202 },
]

// 剂量判定 → 短标签与徽章（判定基于推断浓度，估计值）
const VERDICT_LABEL = {
  effective: '剂量达标',
  insufficient: '剂量不足',
  uncertain: '不确定',
  unknown: '未知',
  trace_level: '微量级',
}
const VERDICT_BADGE = {
  effective: 'badge-ok',
  insufficient: 'badge-danger',
  uncertain: 'badge-warn',
  unknown: 'badge-muted',
  trace_level: 'badge-warn',
}

const pick = (p) => ({ id: p.id, name: p.name, brand: p.brand })

// 可搜索产品选择器（手写 combobox：输入过滤 + 键盘上下/回车选中，不引组件库）
function ProductCombobox({ label, selected, onSelect, excludeId }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [items, setItems] = useState(null)
  const [hi, setHi] = useState(0)
  const seq = useRef(0) // reqSeq 防过期响应覆盖
  const boxRef = useRef(null)

  // 输入过滤（200ms 防抖；只认最新一次响应）
  useEffect(() => {
    if (!open || selected) return undefined
    const my = ++seq.current
    const t = setTimeout(() => {
      api.products({ q, limit: 10 })
        .then((r) => {
          if (my !== seq.current) return
          setItems((r.items ?? r).filter((p) => p.id !== excludeId))
          setHi(0)
        })
        .catch(() => { if (my === seq.current) setItems([]) })
    }, 200)
    return () => { clearTimeout(t); seq.current += 1 }
  }, [q, open, selected, excludeId])

  // 点击外部收起
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const choose = (p) => {
    onSelect(pick(p))
    setOpen(false)
    setQ('')
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) setOpen(true)
      else if (items && items.length) setHi((hi + 1) % items.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (items && items.length) setHi((hi - 1 + items.length) % items.length)
    } else if (e.key === 'Enter') {
      if (open && items && items[hi]) { e.preventDefault(); choose(items[hi]) }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="flex-1 min-w-[220px]" ref={boxRef}>
      <div className="kv-label mb-1.5">{label}</div>
      <div className="relative">
        {selected ? (
          <div className="input flex items-center justify-between gap-2">
            <span className="truncate">
              {selected.brand ? `${selected.brand} · ` : ''}{selected.name || `#${selected.id}`}
            </span>
            <button
              type="button"
              className="text-ink-3 hover:text-ink flex-shrink-0"
              aria-label={`清除${label}`}
              onClick={() => onSelect(null)}
            >
              ✕
            </button>
          </div>
        ) : (
          <input
            className="input"
            placeholder="输入产品名或品牌搜索…"
            value={q}
            onChange={(e) => { setQ(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
          />
        )}
        {open && !selected && (
          <div className="absolute z-20 mt-1 w-full bg-card border border-line rounded-xl shadow-card max-h-64 overflow-y-auto">
            {items === null ? (
              <div className="px-3 py-2 text-sm text-ink-3">搜索中…</div>
            ) : items.length === 0 ? (
              <div className="px-3 py-2 text-sm text-ink-3">无匹配产品</div>
            ) : (
              items.map((p, i) => (
                <button
                  key={p.id}
                  type="button"
                  className={`w-full text-left px-3 py-2 text-sm ${i === hi ? 'bg-rosewood/10' : ''}`}
                  onMouseDown={(e) => { e.preventDefault(); choose(p) }}
                  onMouseEnter={() => setHi(i)}
                >
                  {p.brand} · {p.name}
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// 取每起效成本最低值（估计）：无推断/无折算数据返回 null
function minCost(conc) {
  if (!conc || !conc.inferred) return null
  let best = null
  for (const e of conc.estimates || []) {
    const v = e.cost_per_effective_dose
    if (v != null && (!best || v < best.value)) best = { value: v, ingredient: e.cn_name || e.inci_name }
  }
  return best
}

// 每成分剂量判定集合（两产品都已推断时才参与 diff）
function verdictMap(conc) {
  if (!conc || !conc.inferred) return null
  const m = new Map()
  for (const e of conc.estimates || []) {
    m.set(e.ingredient_id, [...new Set((e.dose || []).map((d) => d.verdict))])
  }
  return m
}

// inferred=false 表示该侧产品未做浓度推断（无判定可言），与「已推断但无功效断言」区分开
function VerdictBadges({ verdicts, inferred = true }) {
  if (!inferred) return <span className="badge-muted">未推断</span>
  if (!verdicts || verdicts.length === 0) return <span className="badge-muted">含</span>
  return (
    <span className="flex flex-wrap gap-1 justify-end">
      {verdicts.map((v) => (
        <span key={v} className={VERDICT_BADGE[v] || 'badge-muted'}>{VERDICT_LABEL[v] || v}</span>
      ))}
    </span>
  )
}

export default function Compare() {
  const [params, setParams] = useSearchParams()
  const validId = (value) => Number.isInteger(Number(value)) && Number(value) > 0 ? Number(value) : null
  const aId = validId(params.get('a'))
  const bId = validId(params.get('b')) === aId ? null : validId(params.get('b'))
  const a = useFetch(() => aId ? api.product(aId) : Promise.resolve(null), [aId])
  const b = useFetch(() => bId ? api.product(bId) : Promise.resolve(null), [bId])
  const detailA = a.data?.id === aId ? a.data : null
  const detailB = b.data?.id === bId ? b.data : null
  const ca = useFetch(() => aId ? api.productConcentration(aId) : Promise.resolve(null), [aId])
  const cb = useFetch(() => bId ? api.productConcentration(bId) : Promise.resolve(null), [bId])
  const pa = useFetch(() => aId ? api.productEvidenceProfile(aId) : Promise.resolve(null), [aId])
  const pb = useFetch(() => bId ? api.productEvidenceProfile(bId) : Promise.resolve(null), [bId])
  const [tab, setTab] = useState('different')
  const [simLoading, setSimLoading] = useState(false)
  const [simNote, setSimNote] = useState(null)
  const lookupSeq = useRef(0)
  useEffect(() => {
    lookupSeq.current += 1
    setSimLoading(false)
    setSimNote(null)
    setTab('different')
    return () => { lookupSeq.current += 1 }
  }, [aId, bId])

  function choose(side, product) {
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      if (product) next.set(side, String(product.id))
      else next.delete(side)
      return next
    })
  }

  async function fillFromSimilar() {
    if (!aId || simLoading) return
    const request = ++lookupSeq.current
    setSimLoading(true)
    try {
      const data = await api.productSimilarLevels(aId, { k: 5 })
      if (request !== lookupSeq.current) return
      const first = data.l1.find((p) => p.id !== aId && p.id !== bId)
      if (first) choose('b', first)
      else setSimNote('暂无成分相似产品')
    } catch {
      if (request === lookupSeq.current) setSimNote('相似产品加载失败')
    } finally {
      if (request === lookupSeq.current) setSimLoading(false)
    }
  }

  const rows = useMemo(() => {
    if (!detailA || !detailB) return []
    const mapA = new Map(detailA.ingredients.map((i) => [i.ingredient_id, i]))
    const mapB = new Map(detailB.ingredients.map((i) => [i.ingredient_id, i]))
    return [...new Set([...mapA.keys(), ...mapB.keys()])].map((id) => ({
      ing: mapA.get(id) || mapB.get(id), inA: mapA.has(id), inB: mapB.has(id),
    }))
  }, [detailA, detailB])
  const shared = rows.filter((r) => r.inA && r.inB)
  const different = rows.filter((r) => !r.inA || !r.inB)
  const visible = tab === 'shared' ? shared : tab === 'all' ? rows : different
  const costA = useMemo(() => minCost(ca.data), [ca.data])
  const costB = useMemo(() => minCost(cb.data), [cb.data])
  const vA = verdictMap(ca.data), vB = verdictMap(cb.data)
  const unitComparable = detailA?.unit_price != null && detailB?.unit_price != null
    && detailA.unit_price_unit === detailB.unit_price_unit

  return (
    <div className="pearl-page">
      <div className="glass-card">
        <h1 className="pearl-title">选择两款产品对比成分</h1>
        <p className="text-sm text-pearl-ink-2 mb-4">看共有与不同成分，再比较价格和证据。成分相近不代表功效等同。</p>
        <div className="flex flex-col md:flex-row gap-4">
          <ProductCombobox label="产品 A" selected={detailA || (aId ? { id: aId } : null)} onSelect={(p) => choose('a', p)} excludeId={bId} />
          <ProductCombobox label="产品 B" selected={detailB || (bId ? { id: bId } : null)} onSelect={(p) => choose('b', p)} excludeId={aId} />
        </div>
        <div className="flex flex-wrap items-center gap-3 mt-4 text-xs text-pearl-ink-3">
          <span>快速试试：</span>
          {PRESETS.map((p) => <button key={p.label} type="button" className="btn-page" onClick={() => setParams({ a: String(p.a), b: String(p.b) })}>{p.label}</button>)}
          {aId && !bId && <button type="button" className="btn-page" disabled={simLoading} onClick={fillFromSimilar}>{simLoading ? '查找中…' : '从相似产品里挑'}</button>}
          {simNote && <span>{simNote}</span>}
        </div>
      </div>

      {(a.error || b.error) && <p className="pearl-notice">产品加载失败，请重新选择或稍后重试。</p>}
      {(!detailA || !detailB) && <p className="glass-card text-sm text-pearl-ink-3">{(aId && a.loading) || (bId && b.loading) ? '产品加载中…' : '选定两款产品后，查看共有成分、差异成分、价格与证据。'}</p>}

      {detailA && detailB && <>
        <section className="glass-card">
          <h2 className="pearl-title">价格与规格</h2>
          <div className="grid md:grid-cols-2 gap-4">
            {[detailA, detailB].map((product, i) => <div key={product.id} className="fairy-panel p-4">
              <p className="text-xs text-pearl-ink-3 mb-2">产品 {i === 0 ? 'A' : 'B'}</p>
              <Link to={`/products/${product.id}`} className="block text-sm font-semibold mb-3 hover:underline">{product.name}</Link>
              <PriceInfo product={product} />
            </div>)}
          </div>
          <p className="text-xs text-pearl-ink-3 mt-3">{unitComparable ? `两款均按元/${detailA.unit_price_unit}展示单位价。` : '规格缺失或计量单位不同，暂不比较单位价；不将克换算成毫升。'}参考价可能来自不同日期或渠道，具体以来源为准。</p>
        </section>

        <section className="glass-card">
          <h2 className="pearl-title">成分对比</h2>
          <div className="flex flex-wrap gap-2 mb-4">
            {[['different', `差异成分（${different.length}）`], ['shared', `共有成分（${shared.length}）`], ['all', `全部成分（${rows.length}）`]].map(([value, label]) => <button key={value} type="button" aria-pressed={tab === value} className={tab === value ? 'fairy-chip !bg-rosewood !text-white' : 'fairy-chip'} onClick={() => setTab(value)}>{label}</button>)}
          </div>
          {!visible.length ? <p className="text-sm text-pearl-ink-3">{tab === 'different' ? '两款产品的成分集合一致；含量与实际效果仍可能不同。' : '暂无共有成分。'}</p> : <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-sm">
              <thead><tr><th className="th">成分</th><th className="th">产品 A</th><th className="th">产品 B</th></tr></thead>
              <tbody>{visible.map((r) => <tr key={r.ing.ingredient_id}>
                <td className="td"><Link to={`/ingredients/${r.ing.ingredient_id}`} className="text-rosewood hover:underline">{r.ing.cn_name || r.ing.inci_name}</Link></td>
                <td className="td whitespace-nowrap">{r.inA ? '含有' : '未列出'}</td><td className="td whitespace-nowrap">{r.inB ? '含有' : '未列出'}</td>
              </tr>)}</tbody>
            </table>
          </div>}
        </section>

        <section className="glass-card">
          <h2 className="pearl-title">证据差异</h2>
          <div className="grid md:grid-cols-2 gap-4">{[[detailA, pa], [detailB, pb]].map(([product, state]) => <div key={product.id} className="fairy-panel p-4">
            <h3 className="text-sm font-semibold mb-3">{product.name}</h3>
            <EvidenceSummary state={state} />
            <Link to={`/products/${product.id}`} className="block text-xs text-rosewood mt-3 hover:underline">查看具体来源与功效宣称 →</Link>
          </div>)}</div>
        </section>

        <details className="glass-card">
          <summary className="pearl-title cursor-pointer">剂量与每起效成本（估计）</summary>
          <div className="grid md:grid-cols-2 gap-4">{[[detailA, costA, ca], [detailB, costB, cb]].map(([product, cost, state]) => <div key={product.id} className="fairy-panel p-4">
            <h3 className="text-sm font-semibold mb-2">{product.name}</h3>
            <p className="text-sm">{state.loading ? '加载中…' : state.error ? '剂量数据加载失败' : cost ? `每起效成本 ¥${cost.value.toFixed(2)}/天（估计；成分：${cost.ingredient}）` : '暂无成本数据'}</p>
          </div>)}</div>
          <p className="text-xs text-pearl-ink-3 my-3">按 1ml 日用量折算，取有折算数据成分中的最低值，不同成分的数值不代表同等功效成本。</p>
          <div className="space-y-2">{rows.filter((r) => vA?.has(r.ing.ingredient_id) || vB?.has(r.ing.ingredient_id)).map((r) => <div key={r.ing.ingredient_id} className="grid grid-cols-3 gap-2 text-xs">
            <span>{r.ing.cn_name || r.ing.inci_name}</span>
            {r.inA ? <VerdictBadges verdicts={vA?.get(r.ing.ingredient_id)} inferred={!!vA} /> : <span>未列出</span>}
            {r.inB ? <VerdictBadges verdicts={vB?.get(r.ing.ingredient_id)} inferred={!!vB} /> : <span>未列出</span>}
          </div>)}</div>
        </details>
      </>}
    </div>
  )
}
