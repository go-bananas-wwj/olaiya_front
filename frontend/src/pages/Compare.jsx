import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'

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
    return () => clearTimeout(t)
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

const sameVerdicts = (a, b) => a.length === b.length && a.every((v) => b.includes(v))

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
  const [selA, setSelA] = useState(null) // {id, name, brand}
  const [selB, setSelB] = useState(null)
  const [detailA, setDetailA] = useState(null)
  const [detailB, setDetailB] = useState(null)
  const [concA, setConcA] = useState(null)
  const [concB, setConcB] = useState(null)
  const [showAll, setShowAll] = useState(false)
  const [simLoading, setSimLoading] = useState(false)
  const [simNote, setSimNote] = useState(null)
  // 支持 #/compare?a=1&b=2 预选（产品详情页「加入对比」跳入；HashRouter 下 query 在 hash 内）
  const [searchParams] = useSearchParams()
  const didInit = useRef(false)

  // URL 预选（仅初始化执行一次）
  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    const a = Number(searchParams.get('a'))
    const b = Number(searchParams.get('b'))
    if (Number.isInteger(a) && a > 0) {
      api.product(a).then((p) => { setSelA(pick(p)); setDetailA(p) }).catch(() => {})
    }
    if (Number.isInteger(b) && b > 0 && b !== a) {
      api.product(b).then((p) => { setSelB(pick(p)); setDetailB(p) }).catch(() => {})
    }
  }, [searchParams])

  useEffect(() => {
    if (!selA) { setDetailA(null); return }
    if (detailA?.id === selA.id) return
    api.product(selA.id).then(setDetailA).catch(() => {})
  }, [selA, detailA])
  useEffect(() => {
    if (!selB) { setDetailB(null); return }
    if (detailB?.id === selB.id) return
    api.product(selB.id).then(setDetailB).catch(() => {})
  }, [selB, detailB])

  useEffect(() => {
    setConcA(null)
    if (selA?.id) api.productConcentration(selA.id).then(setConcA).catch(() => {})
  }, [selA?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setConcB(null)
    if (selB?.id) api.productConcentration(selB.id).then(setConcB).catch(() => {})
  }, [selB?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setSimNote(null) }, [selA?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // 相似填充：similar-levels L1（成分集合 Jaccard）首个填 B 槽
  const fillFromSimilar = () => {
    if (!selA || simLoading) return
    setSimLoading(true)
    setSimNote(null)
    api.productSimilarLevels(selA.id, { k: 5 })
      .then((r) => {
        const first = (r.l1 || []).find((p) => p.id !== selA.id && p.id !== selB?.id)
        if (first) {
          setSelB(pick(first))
          setSimNote(`已填入成分集合相似产品（Jaccard ${first.score}，共有 ${first.shared} 种成分）`)
        } else {
          setSimNote('暂无成分相似产品')
        }
      })
      .catch(() => setSimNote('相似产品加载失败'))
      .finally(() => setSimLoading(false))
  }

  // 预设组一键对比
  const applyPreset = (preset) => {
    setSelA(null); setSelB(null)
    Promise.all([api.product(preset.a), api.product(preset.b)])
      .then(([pa, pb]) => {
        setSelA(pick(pa)); setDetailA(pa)
        setSelB(pick(pb)); setDetailB(pb)
      })
      .catch(() => {})
  }

  const costA = useMemo(() => minCost(concA), [concA])
  const costB = useMemo(() => minCost(concB), [concB])

  // 成分 diff 行：默认只显示差异行（一款独有 / 剂量判定不同），开关显示全部
  const bothInferred = !!(concA?.inferred && concB?.inferred)
  const rows = useMemo(() => {
    if (!detailA || !detailB) return null
    const mapB = new Map(detailB.ingredients.map((i) => [i.ingredient_id, i]))
    const vA = verdictMap(concA)
    const vB = verdictMap(concB)
    const both = vA !== null && vB !== null
    const out = []
    const seen = new Set()
    for (const i of detailA.ingredients) {
      seen.add(i.ingredient_id)
      const inB = mapB.has(i.ingredient_id)
      const va = vA?.get(i.ingredient_id) ?? []
      const vb = inB ? (vB?.get(i.ingredient_id) ?? []) : []
      const verdictDiff = inB && both && !sameVerdicts(va, vb)
      out.push({
        ing: i,
        inA: true,
        inB,
        va,
        vb,
        inferredA: vA !== null,
        inferredB: vB !== null,
        only: inB ? null : 'A',
        isDiff: !inB || verdictDiff,
        hasEvidence: i.has_evidence || (inB && mapB.get(i.ingredient_id).has_evidence),
      })
    }
    for (const i of detailB.ingredients) {
      if (seen.has(i.ingredient_id)) continue
      out.push({
        ing: i, inA: false, inB: true, va: [], vb: vB?.get(i.ingredient_id) ?? [],
        inferredA: vA !== null, inferredB: vB !== null,
        only: 'B', isDiff: true, hasEvidence: i.has_evidence,
      })
    }
    return out
  }, [detailA, detailB, concA, concB])

  const diffCount = useMemo(() => (rows ? rows.filter((r) => r.isDiff).length : 0), [rows])
  const visibleRows = rows ? (showAll ? rows : rows.filter((r) => r.isDiff)) : null

  return (
    <div>
      <div className="card">
        <h2 className="card-title">选择两款产品对比成分</h2>
        <div className="flex flex-col md:flex-row gap-4">
          <ProductCombobox label="产品 A" selected={selA} onSelect={setSelA} excludeId={selB?.id} />
          <ProductCombobox label="产品 B" selected={selB} onSelect={setSelB} excludeId={selA?.id} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
          <span className="text-ink-3">快速试试：</span>
          {PRESETS.map((p) => (
            <button key={p.label} type="button" className="btn-page" onClick={() => applyPreset(p)}>
              {p.label}
            </button>
          ))}
          {selA && !selB && (
            <>
              <span className="text-ink-3">不知道和谁比？→</span>
              <button type="button" className="btn-page" onClick={fillFromSimilar} disabled={simLoading}>
                {simLoading ? '查找中…' : '从相似产品里挑'}
              </button>
            </>
          )}
          {simNote && <span className="text-xs text-ink-3">{simNote}</span>}
        </div>
      </div>

      {(!detailA || !detailB) && (
        <div className="bg-card rounded-card shadow-card py-16 px-8 text-center text-ink-3 text-sm">
          搜索并选定两款产品后，这里会展示每起效成本与成分差异
        </div>
      )}

      {detailA && detailB && (
        <div className="card">
          <h2 className="card-title">每起效成本（估计）</h2>
          <div className="grid md:grid-cols-2 gap-5">
            {[
              ['A', detailA, costA],
              ['B', detailB, costB],
            ].map(([tag, detail, cost]) => (
              <div key={tag} className="border border-line rounded-xl px-4 py-3">
                <div className="kv-label mb-1">产品 {tag}</div>
                <div className="text-xs text-ink-3 mb-2 truncate">
                  <Link to={`/products/${detail.id}`} className="text-brand hover:underline">
                    {detail.brand} · {detail.name}
                  </Link>
                </div>
                {cost ? (
                  <div>
                    <span className="font-num text-4xl font-bold text-rosewood tabular-nums">
                      ¥{cost.value.toFixed(2)}
                    </span>
                    <span className="text-sm text-ink-3 ml-1">/天（估计）</span>
                    <div className="text-xs text-ink-3 mt-1">最低起效成本成分：{cost.ingredient}</div>
                  </div>
                ) : (
                  <div className="py-2"><span className="badge-muted">暂无成本数据</span></div>
                )}
              </div>
            ))}
          </div>
          <div className="text-xs text-ink-3 mt-3 leading-relaxed">
            按 1ml 日用量折算的每日使用成本（估计值，非实测），取该产品有折算数据的成分中最低值；
            无官方降序成分表或缺价格/起效浓度数据时如实标注「暂无成本数据」。
          </div>
        </div>
      )}

      {detailA && detailB && visibleRows && (
        <div className="card">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
            <h2 className="card-title !mb-0">成分对比</h2>
            <button type="button" className="btn-page" onClick={() => setShowAll((v) => !v)}>
              {showAll ? `只看差异（${diffCount} 行）` : `显示全部 ${rows.length} 种`}
            </button>
          </div>
          <div className="notice">
            默认只显示差异行：一款独有，或剂量判定不同（判定基于推断浓度，估计值）。
          </div>
          {visibleRows.length === 0 ? (
            <div className="notice !mb-0">
              {bothInferred
                ? '两款产品成分与剂量判定完全一致。'
                : '两款产品成分完全一致（剂量判定数据不足，未对比）。'}
            </div>
          ) : (
            <div className="border border-line rounded-xl overflow-hidden max-h-[520px] overflow-y-auto">
              <div className="grid grid-cols-[1fr_auto_auto] items-center gap-2 px-3 py-2 border-b border-line text-xs text-ink-3">
                <div>成分</div>
                <div className="w-28 text-right">产品 A</div>
                <div className="w-28 text-right">产品 B</div>
              </div>
              {visibleRows.map((r) => (
                <div
                  key={r.ing.ingredient_id}
                  className="grid grid-cols-[1fr_auto_auto] items-center gap-2 px-3 py-2 border-b border-line last:border-0 text-sm"
                >
                  <div className="min-w-0 flex items-center gap-1.5 flex-wrap">
                    {r.hasEvidence ? (
                      <Link to={`/ingredients/${r.ing.ingredient_id}`} className="text-brand hover:underline font-medium">
                        {r.ing.cn_name || r.ing.inci_name}
                      </Link>
                    ) : (
                      <span>{r.ing.cn_name || r.ing.inci_name}</span>
                    )}
                    {r.only && <span className="badge-muted">仅 {r.only}</span>}
                  </div>
                  <div className="w-28 text-right">
                    {r.inA ? <VerdictBadges verdicts={r.va} inferred={r.inferredA} /> : <span className="text-ink-3">—</span>}
                  </div>
                  <div className="w-28 text-right">
                    {r.inB ? <VerdictBadges verdicts={r.vb} inferred={r.inferredB} /> : <span className="text-ink-3">—</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
