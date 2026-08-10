import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from '../components/common'
import ClaimCard from '../components/ClaimCard'
import ConcentrationPanel from '../components/ConcentrationPanel'
import SimilarLevels from '../components/SimilarLevels'

// —— 宣称 ↔ 剂量判定匹配（纯前端聚合现有 API 字段，不伪造）——
// 宣称文本与 dose.efficacy 都可能带「（…）」补充说明，取括号前主干做双向包含匹配
const stem = (s) => (s || '').split(/[（(]/)[0].trim()

function matchDoses(claimText, estimates) {
  if (!estimates) return []
  const c = stem(claimText)
  if (!c) return []
  const out = []
  for (const est of estimates) {
    for (const d of est.dose || []) {
      const e = stem(d.efficacy)
      if (e && (e.includes(c) || c.includes(e))) out.push({ est, d })
    }
  }
  return out
}

// 单条宣称的聚合判定（保守优先：不足 > 存疑 > 达标；无匹配 = 无法判定）
function claimStatus(doses) {
  if (!doses || doses.length === 0) return 'unknown'
  const vs = doses.map(({ d }) => d.verdict)
  if (vs.includes('insufficient')) return 'insufficient'
  if (vs.includes('uncertain') || vs.includes('trace_level')) return 'uncertain'
  if (vs.includes('effective')) return 'effective'
  return 'unknown'
}

// —— 核验结论条（判决卡）：聚合宣称与浓度判定，点击锚点滚动 ——
const STATUS_META = {
  effective: { text: '剂量达标', cls: 'pearl-badge-ok' },
  uncertain: { text: '剂量存疑', cls: 'pearl-badge-warn' },
  insufficient: { text: '剂量不足', cls: 'pearl-badge-bad' },
  unknown: { text: '无法判定', cls: 'pearl-badge-muted' },
}

function scrollTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function VerdictBar({ claims, conc }) {
  const estimates = conc.data?.inferred ? conc.data.estimates : null
  const enriched = claims.map((c, i) => {
    const doses = matchDoses(c.claim, estimates)
    return { claim: c, i, doses, status: claimStatus(doses) }
  })
  const counts = { effective: 0, uncertain: 0, insufficient: 0, unknown: 0 }
  for (const e of enriched) counts[e.status] += 1

  // 宣称分组展示：同状态相邻，组内保持原顺序
  const ordered = ['effective', 'uncertain', 'insufficient', 'unknown']
    .flatMap((s) => enriched.filter((e) => e.status === s))

  return (
    <div className="glass-card">
      <h2 className="pearl-title">核验结论</h2>
      <div className="text-sm text-pearl-ink-2 leading-relaxed">
        <b className="font-num">{claims.length}</b> 条宣称：
        <b className="text-[#3d7a54] font-num mx-1">{counts.effective}</b>条剂量达标 ·
        <b className="text-[#a06818] font-num mx-1">{counts.uncertain}</b>条剂量存疑 ·
        <b className="text-[#a04a4a] font-num mx-1">{counts.insufficient}</b>条剂量不足 ·
        <b className="text-pearl-ink-3 font-num mx-1">{counts.unknown}</b>条无法判定
      </div>
      {conc.loading ? (
        <div className="mt-2 text-xs text-pearl-ink-3 leading-relaxed">浓度数据加载中…</div>
      ) : conc.error ? (
        <div className="mt-2 text-xs text-pearl-ink-3 leading-relaxed">浓度数据加载失败，剂量判定暂不可用——不猜测。</div>
      ) : !estimates && (
        <div className="mt-2 text-xs text-pearl-ink-3 leading-relaxed">
          该产品无浓度推断数据（无官方降序成分表），宣称剂量一律「无法判定」——查不到本身也是信号，不做猜测。
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {ordered.map((e) => (
          <button
            key={e.i}
            type="button"
            onClick={() => scrollTo(`claim-${e.i}`)}
            className={`${STATUS_META[e.status].cls} cursor-pointer hover:brightness-95 transition`}
            title="点击滚动到对应宣称卡"
          >
            {e.claim.claim}
          </button>
        ))}
      </div>
      <div className="mt-2 text-xs text-pearl-ink-3 leading-relaxed">
        判定口径：宣称按功效主干词匹配成分剂量判定，命中多条时取最差档（宁保守、不错放）。
      </div>
    </div>
  )
}

// —— 成分表 skim 模式：有证据优先置顶，默认前 8 行 ——
const SKIM_COUNT = 8

function IngredientTable({ ingredients }) {
  const [expanded, setExpanded] = useState(false)
  const [showInci, setShowInci] = useState(false)
  const sorted = [...ingredients].sort((a, b) =>
    (b.has_evidence - a.has_evidence) || ((a.position ?? 1e9) - (b.position ?? 1e9)))
  const visible = expanded ? sorted : sorted.slice(0, SKIM_COUNT)
  const hidden = sorted.length - visible.length

  return (
    <div className="glass-card">
      <h2 className="pearl-title">产品成分表（{ingredients.length} 种）</h2>
      <div className="pearl-notice">
        带 <span className="pearl-badge-ok mx-1">有文献证据</span> 徽章的成分在证据库中有功效断言与文献支撑，点击查看证据链。
        「安全风险/活性/使用目的」为镜像站标注列。
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-pearl-ink-3 font-semibold text-xs px-2.5 py-2 border-b-2 border-[rgba(138,90,106,0.18)] whitespace-nowrap">
                成分名称
                <button
                  type="button"
                  onClick={() => setShowInci((v) => !v)}
                  className="ml-2 text-iris hover:underline font-normal"
                >
                  {showInci ? '收起英文原名' : '展开看英文原名'}
                </button>
              </th>
              <th className="text-left text-pearl-ink-3 font-semibold text-xs px-2.5 py-2 border-b-2 border-[rgba(138,90,106,0.18)]">安全风险</th>
              <th className="text-left text-pearl-ink-3 font-semibold text-xs px-2.5 py-2 border-b-2 border-[rgba(138,90,106,0.18)]">活性成分</th>
              <th className="text-left text-pearl-ink-3 font-semibold text-xs px-2.5 py-2 border-b-2 border-[rgba(138,90,106,0.18)]">使用目的</th>
              <th className="text-left text-pearl-ink-3 font-semibold text-xs px-2.5 py-2 border-b-2 border-[rgba(138,90,106,0.18)]">证据</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((ing) => (
              <tr key={ing.ingredient_id} className={ing.has_evidence ? 'bg-[rgba(126,200,150,0.1)] hover:bg-[rgba(126,200,150,0.2)]' : 'hover:bg-white/40'}>
                <td className="px-2.5 py-2 border-b border-[rgba(138,90,106,0.1)] text-sm align-top">
                  {ing.has_evidence ? (
                    <Link to={`/ingredients/${ing.ingredient_id}`} className="text-rosewood font-medium hover:underline">
                      {ing.cn_name || ing.inci_name}
                    </Link>
                  ) : (
                    ing.cn_name || ing.inci_name
                  )}
                  {showInci && ing.inci_name && ing.cn_name && ing.inci_name !== ing.cn_name && (
                    <div className="text-xs text-pearl-ink-3">{ing.inci_name}</div>
                  )}
                </td>
                <td className="px-2.5 py-2 border-b border-[rgba(138,90,106,0.1)] text-sm align-top font-num tabular-nums">{ing.safety_risk ?? '—'}</td>
                <td className="px-2.5 py-2 border-b border-[rgba(138,90,106,0.1)] text-sm align-top">
                  {ing.is_active
                    ? <span className="text-[#3d7a54] font-semibold">活性</span>
                    : <span className="text-pearl-ink-3">—</span>}
                </td>
                <td className="px-2.5 py-2 border-b border-[rgba(138,90,106,0.1)] text-sm align-top">{ing.purpose ?? '—'}</td>
                <td className="px-2.5 py-2 border-b border-[rgba(138,90,106,0.1)] text-sm align-top">
                  {ing.has_evidence
                    ? <Link to={`/ingredients/${ing.ingredient_id}`} className="pearl-badge-ok hover:ring-1 hover:ring-mint">有文献证据 →</Link>
                    : <span className="text-pearl-ink-3 text-xs">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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

export default function ProductDetail() {
  const { id } = useParams()
  const { data: p, loading, error } = useFetch(() => api.product(id), [id])
  // 浓度数据页面级预取：判决条 / 宣称卡 hero / 浓度区块共用同一份
  const conc = useFetch(() => api.productConcentration(id), [id])

  if (loading) return <div className="pearl-page"><div className="glass-card relative"><Loading /></div></div>
  if (error) return <div className="pearl-page"><div className="glass-card relative"><LoadError error={error} /></div></div>

  // 备案人/备案日期/来源为后端结构化字段；note 仅含功效描述，提取功效词
  const effMatch = (p.note || '').match(/功效: ([^（；]*)/)
  const kv = [
    p.registrant && ['备案人', p.registrant],
    p.filing_date && ['备案日期', p.filing_date],
    effMatch && ['宣称功效', effMatch[1]],
    p.price_current != null && ['参考价（人工采样）', `¥${p.price_current}${p.spec ? ` / ${p.spec}` : ''}`],
    p.price_current == null && p.spec && ['主规格', p.spec],
  ].filter(Boolean)

  const estimates = conc.data?.inferred ? conc.data.estimates : null

  return (
    <div className="pearl-page">
      <div className="relative">
        <Link to="/products" className="text-sm text-rosewood hover:underline">← 返回产品库</Link>

        {/* 产品头卡 */}
        <div className="glass-card mt-3">
          <div className="font-display text-2xl md:text-3xl grad-text tracking-wide inline-block">{p.name}</div>
          <div className="text-[13px] text-pearl-ink-2 mt-2 flex flex-wrap gap-x-4 gap-y-1">
            <span>品牌：<b>{p.brand}</b></span>
            {p.nmpa_id && <span>备案号：<b>{p.nmpa_id}</b></span>}
            {p.category && <span>类别：{p.category}</span>}
          </div>
          {kv.length > 0 && (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 mt-4">
              {kv.map(([k, v]) => (
                <div key={k} className="fairy-panel px-3.5 py-2.5">
                  <div className="text-pearl-ink-3 text-xs mb-0.5">{k}</div>
                  <div className="text-pearl-ink text-[13px] break-all">{v}</div>
                </div>
              ))}
            </div>
          )}
          {p.source_url && (
            <div className="text-xs text-pearl-ink-3 mt-4 break-all">
              备案数据来源：
              <a href={p.source_url} target="_blank" rel="noreferrer" className="text-iris hover:underline">
                {p.source_url}
              </a>
              （NMPA 公示镜像）
            </div>
          )}
        </div>

        {/* 核验结论条（判决卡） */}
        {p.claims.length > 0 && <VerdictBar claims={p.claims} conc={conc} />}

        {/* 宣称核验区：每张卡 hero 位带剂量对照条 */}
        <div className="glass-card">
          <h2 className="pearl-title">功效宣称依据（{p.claims.length} 条）</h2>
          {p.claims.length === 0 ? (
            <div className="pearl-notice !mb-0">
              该产品备案页未公示《功效宣称依据摘要》（可能属 2021 年前备案或清洁/物理遮盖等法定免公布情形）
              ——「查不到摘要」本身也是核验信号。
            </div>
          ) : (
            p.claims.map((c, i) => (
              <ClaimCard
                key={i}
                claim={c}
                nmpaId={p.nmpa_id}
                anchorId={`claim-${i}`}
                doses={matchDoses(c.claim, estimates)}
              />
            ))
          )}
        </div>

        <ConcentrationPanel conc={conc} />

        <IngredientTable ingredients={p.ingredients} />

        <SimilarLevels productId={id} />
      </div>
    </div>
  )
}
