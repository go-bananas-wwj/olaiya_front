import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from '../components/common'
import AssertionCard from '../components/AssertionCard'

// 先验字段（IECIC/CIR/SCCS 等外部数据库登记值），有值才展示
const PRIOR_DEFS = [
  ['iecic_max_leave_on', 'IECIC 淋洗外（驻留类）上限', '%'],
  ['iecic_max_rinse_off', 'IECIC 淋洗类上限', '%'],
  ['legal_cap', '法规限用上限', '%'],
  ['cir_conc_low', 'CIR 安全浓度下限', '%'],
  ['cir_conc_high', 'CIR 安全浓度上限', '%'],
  ['sccs_limit', 'SCCS 限值', '%'],
]

// D3 透皮判定徽章：verdict → 文案与样式（判定语义为理化模型估计）
const TRANSDERMAL_DEFS = {
  easy: { text: '易透皮（估计）', cls: 'badge-ok' },
  medium: { text: '透皮中等（估计）', cls: 'badge-warn' },
  hard: { text: '难透皮（估计）', cls: 'badge-danger' },
  not_applicable: { text: '透皮判定不适用', cls: 'badge-muted' },
}

export default function IngredientDetail() {
  const { id } = useParams()
  const { data: ing, loading, error } = useFetch(() => api.ingredient(id), [id])

  if (loading) return <div className="card"><Loading /></div>
  if (error) return <div className="card"><LoadError error={error} /></div>

  const priors = PRIOR_DEFS
    .map(([key, label, unit]) => ing.priors?.[key] != null && [label, `${ing.priors[key]}${unit}`])
    .filter(Boolean)

  const td = ing.transdermal
    && (TRANSDERMAL_DEFS[ing.transdermal.verdict] || TRANSDERMAL_DEFS.not_applicable)

  return (
    <div>
      <Link to="/ingredients" className="text-sm text-brand hover:underline">← 返回成分库</Link>

      <div className="card mt-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="text-xl md:text-2xl font-bold">{ing.cn_name || ing.inci_name}</div>
          {ing.assertions.length > 0
            ? <span className="badge-ok">有文献证据 · 断言 {ing.assertions.length} 条</span>
            : <span className="badge-muted">暂无功效断言</span>}
          {td && <span className={td.cls} title={ing.transdermal.reason}>透皮 · {td.text}</span>}
        </div>
        <div className="text-[13px] text-ink-2 mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {ing.inci_name && <span>INCI：<b className="break-all">{ing.inci_name}</b></span>}
          {ing.cas_no && <span>CAS 号：{ing.cas_no}</span>}
        </div>
        {ing.transdermal && (
          <div className="mt-2 text-xs text-ink-3 leading-relaxed">
            <div>
              {ing.transdermal.reason}
              {ing.transdermal.logkp != null &&
                `（logKp ≈ ${ing.transdermal.logkp} cm/h，Potts-Guy 估计）`}
            </div>
            <div>{ing.transdermal.disclaimer}</div>
          </div>
        )}
        {priors.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
            {priors.map(([k, v]) => (
              <div key={k} className="bg-bg rounded-[10px] px-3.5 py-2.5">
                <div className="kv-label">{k}</div>
                <div className="kv-value tabular-nums">{v}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">功效断言与证据链（{ing.assertions.length} 条）</h2>
        {ing.assertions.length === 0 ? (
          <div className="notice !mb-0">
            证据库中暂无该成分的功效断言——不代表无效，只代表「我们还没找到可挂接的公开证据」，存疑即标注。
          </div>
        ) : (
          ing.assertions.map((a, i) => <AssertionCard key={i} assertion={a} />)
        )}
      </div>

      <div className="card">
        <h2 className="card-title">含该成分的产品（{ing.products.length} 款）</h2>
        {ing.products.length === 0 ? (
          <div className="text-sm text-ink-3">库内暂无产品使用该成分。</div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-3">
            {ing.products.map((p) => (
              <Link
                key={p.id}
                to={`/products/${p.id}`}
                className="border border-line rounded-xl px-4 py-3 hover:border-brand hover:bg-brand-soft/40 transition-colors"
              >
                <div className="text-sm font-medium leading-snug">{p.name}</div>
                <div className="text-xs text-ink-3 mt-1">{p.brand}</div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
