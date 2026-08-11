import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

// —— 成分速览（INCIDecoder 风格行式列表）——
// skim 模式：有证据成分置顶（其余按 position），默认前 8 行
// 行内展开懒加载成分档案，缓存由父组件持有（换产品时清空）
const SKIM_COUNT = 8

// 起效浓度区间文案：文献值语义，不标注则为估计缺失
function concText(low, high) {
  if (low == null && high == null) return null
  if (low != null && high != null && low !== high) return `${low}–${high}%`
  return `${low ?? high}%`
}

// 单条功效断言：原文照录，不改写
function AssertionRow({ a }) {
  const conc = concText(a.effective_conc_low, a.effective_conc_high)
  return (
    <div className="py-1.5 border-b border-[rgba(138,90,106,0.08)] last:border-b-0">
      <div className="text-[13px] text-pearl-ink leading-relaxed">
        <b>{a.efficacy}</b>
        {conc && <span className="text-pearl-ink-2"> · 起效浓度 <span className="font-num">{conc}</span>（文献值）</span>}
      </div>
      {a.evidence?.title && (
        <div className="text-xs text-pearl-ink-3 leading-relaxed mt-0.5">
          {a.evidence.url ? (
            <a href={a.evidence.url} target="_blank" rel="noreferrer" className="text-iris hover:underline">
              {a.evidence.title} ↗
            </a>
          ) : (
            a.evidence.title
          )}
          {a.evidence.source && <span>（{a.evidence.source}）</span>}
        </div>
      )}
      {a.note && <div className="text-xs text-pearl-ink-3 leading-relaxed mt-0.5">{a.note}</div>}
    </div>
  )
}

// 展开小卡：功效断言 + 安全上限 + 完整档案链接
function IngredientDetailPanel({ entry, ingredientId }) {
  if (!entry || entry.status === 'loading') {
    return <div className="text-xs text-pearl-ink-3 py-2">翻阅证据库中…</div>
  }
  if (entry.status === 'error') {
    return <div className="text-xs text-pearl-ink-3 py-2">成分档案加载失败，稍后再试。</div>
  }
  const d = entry.data
  const priors = d.priors || {}
  const caps = [
    priors.legal_cap != null && `法定上限 ${priors.legal_cap}%`,
    priors.cir_conc_high != null && `CIR 使用浓度至 ${priors.cir_conc_high}%（行业自评）`,
    priors.sccs_limit != null && `SCCS 上限 ${priors.sccs_limit}%`,
  ].filter(Boolean)

  return (
    <div>
      {(d.assertions || []).length === 0 ? (
        <div className="text-xs text-pearl-ink-3 py-2 leading-relaxed">
          证据库暂无该成分功效断言——查不到不编造。
        </div>
      ) : (
        <div>
          {d.assertions.map((a, i) => <AssertionRow key={i} a={a} />)}
        </div>
      )}
      {caps.length > 0 && (
        <div className="text-xs text-pearl-ink-2 leading-relaxed mt-2">
          {caps.join(' · ')}
        </div>
      )}
      <div className="mt-2 text-right">
        <Link to={`/ingredients/${ingredientId}`} className="text-xs text-rosewood hover:underline">
          完整档案 →
        </Link>
      </div>
    </div>
  )
}

function IngredientRow({ ing, rank, open, entry, onToggle }) {
  return (
    <div className="border-b border-[rgba(138,90,106,0.1)] last:border-b-0">
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } }}
        className={`flex items-start gap-2.5 px-2 py-2.5 cursor-pointer transition rounded-xl ${
          ing.has_evidence ? 'bg-[rgba(126,200,150,0.1)] hover:bg-[rgba(126,200,150,0.2)]' : 'hover:bg-white/40'
        }`}
      >
        <span className="font-num text-xs text-pearl-ink-3 pt-1 w-7 flex-shrink-0 tabular-nums">#{rank}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm leading-snug">
            <Link
              to={`/ingredients/${ing.ingredient_id}`}
              onClick={(e) => e.stopPropagation()}
              className="text-rosewood font-medium hover:underline"
            >
              {ing.cn_name || ing.inci_name}
            </Link>
            {ing.inci_name && ing.inci_name !== ing.cn_name && (
              <span className="text-xs text-pearl-ink-3 ml-2 break-all">{ing.inci_name}</span>
            )}
          </div>
          {ing.purpose && (
            <div className="text-xs text-pearl-ink-2 leading-relaxed mt-0.5">{ing.purpose}</div>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0 pt-0.5">
          {ing.has_evidence && <span className="pearl-badge-ok">有证据</span>}
          {ing.is_active && <span className="pearl-badge-iris">活性</span>}
          {ing.safety_risk && (
            <span className="text-xs text-pearl-ink-3 font-num tabular-nums whitespace-nowrap">风险 {ing.safety_risk}</span>
          )}
          <span
            className={`text-pearl-ink-3 text-xs inline-block transition-transform ${open ? 'rotate-90' : ''}`}
            aria-hidden
          >
            ▸
          </span>
        </div>
      </div>
      {open && (
        <div className="fairy-panel mx-2 mb-2.5 px-3.5 py-2.5">
          <IngredientDetailPanel entry={entry} ingredientId={ing.ingredient_id} />
        </div>
      )}
    </div>
  )
}

// cache: { [ingredientId]: { status: 'loading' | 'ok' | 'error', data } }
export default function IngredientList({ ingredients, cache, setCache }) {
  const [expanded, setExpanded] = useState(false)
  const [openIds, setOpenIds] = useState(() => new Set())

  // 换产品（成分列表整体更换）时收起所有展开行
  useEffect(() => {
    setOpenIds(new Set())
    setExpanded(false)
  }, [ingredients])

  const sorted = [...ingredients].sort((a, b) =>
    (b.has_evidence - a.has_evidence) || ((a.position ?? 1e9) - (b.position ?? 1e9)))
  const visible = expanded ? sorted : sorted.slice(0, SKIM_COUNT)
  const hidden = sorted.length - visible.length

  const toggle = (ing) => {
    const id = ing.ingredient_id
    const willOpen = !openIds.has(id)
    setOpenIds((prev) => {
      const next = new Set(prev)
      if (willOpen) next.add(id)
      else next.delete(id)
      return next
    })
    // 懒加载：仅首次展开时请求，已缓存（含失败态）不重复请求
    if (willOpen && !cache[id]) {
      setCache((prev) => ({ ...prev, [id]: { status: 'loading' } }))
      api.ingredient(id, { product_limit: 1 })
        .then((data) => setCache((prev) => ({ ...prev, [id]: { status: 'ok', data } })))
        .catch(() => setCache((prev) => ({ ...prev, [id]: { status: 'error' } })))
    }
  }

  return (
    <div className="glass-card">
      <h2 className="pearl-title">成分速览（{ingredients.length} 种）</h2>
      <div className="pearl-notice">
        点任意成分，看它做什么、证据在哪。绿色 = 证据库有功效文献。
      </div>
      <div>
        {visible.map((ing, i) => (
          <IngredientRow
            key={ing.ingredient_id}
            ing={ing}
            rank={ing.position ?? i + 1}
            open={openIds.has(ing.ingredient_id)}
            entry={cache[ing.ingredient_id]}
            onToggle={() => toggle(ing)}
          />
        ))}
      </div>
      {hidden > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="btn-fairy-ghost mt-3 w-full"
        >
          展开全部 {ingredients.length} 种 ↓
        </button>
      )}
      {expanded && sorted.length > SKIM_COUNT && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="btn-fairy-ghost mt-3 w-full"
        >
          收起 ↑
        </button>
      )}
    </div>
  )
}
