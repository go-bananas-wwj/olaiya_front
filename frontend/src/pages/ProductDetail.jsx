import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from '../components/common'
import ClaimCard from '../components/ClaimCard'
import ConcentrationPanel from '../components/ConcentrationPanel'
import FingerprintBars from '../components/FingerprintBars'
import IngredientList from '../components/IngredientList'
import MatchScore from '../components/MatchScore'
import SimilarLevels from '../components/SimilarLevels'
import PriceInfo from '../components/PriceInfo'
import EvidenceSummary from '../components/EvidenceSummary'

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
        <div className="mt-2 text-xs text-pearl-ink-3 leading-relaxed">浓度数据加载失败，暂不判定。</div>
      ) : !estimates && (
        <div className="mt-2 text-xs text-pearl-ink-3 leading-relaxed">
          无官方降序成分表，宣称剂量一律「无法判定」——查不到不猜测。
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
        口径：宣称匹配成分剂量判定，取最差档（保守）。
      </div>
    </div>
  )
}

export default function ProductDetail() {
  const { id } = useParams()
  const { data: p, loading, error } = useFetch(() => api.product(id), [id])
  const conc = useFetch(() => api.productConcentration(id), [id])
  const fp = useFetch(() => api.productFingerprint(id), [id])
  const profile = useFetch(() => api.productEvidenceProfile(id), [id])
  const [ingCache, setIngCache] = useState({})
  useEffect(() => { setIngCache({}) }, [id])

  if (loading) return <div className="pearl-page"><Loading /></div>
  if (error) return <div className="pearl-page"><LoadError error={error} /></div>
  const estimates = conc.data?.inferred ? conc.data.estimates : null

  return (
    <div className="pearl-page">
      <Link to="/products" className="text-sm text-rosewood hover:underline">← 返回产品库</Link>
      <div className="sticky top-3 z-20 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white/95 px-3 py-2 mt-3 shadow-sm" aria-label="产品快捷操作">
        <a href="#ingredients" onClick={(e) => { e.preventDefault(); scrollTo('ingredients') }} className="btn-page">成分表</a>
        <a href="#similar-products" onClick={(e) => { e.preventDefault(); scrollTo('similar-products') }} className="btn-page">相似与价格</a>
        <a href="#evidence" onClick={(e) => { e.preventDefault(); scrollTo('evidence') }} className="btn-page">功效证据</a>
        <Link to={`/roundtable?product=${encodeURIComponent(p.name)}&product_id=${p.id}`} className="btn-fairy ml-auto">发起圆桌核验</Link>
      </div>

      <div className="glass-card mt-4">
        <h1 className="font-display text-2xl md:text-3xl text-pearl-ink break-words">{p.name}</h1>
        <p className="text-sm text-pearl-ink-2 mt-2">{p.brand}{p.category ? ` · ${p.category}` : ''}</p>
        <div className="mt-4"><PriceInfo product={p} /></div>
        <details className="mt-4 text-xs text-pearl-ink-3">
          <summary className="cursor-pointer">来源与产品信息</summary>
          {p.source_url && <p className="mt-2 break-all">成分信息来源：<a href={p.source_url} target="_blank" rel="noreferrer" className="text-iris hover:underline">{p.source_url}</a></p>}
          {p.nmpa_id && <p className="mt-2">备案号：{p.nmpa_id}</p>}
          {p.registrant && <p className="mt-2">备案人：{p.registrant}</p>}
          {p.filing_date && <p className="mt-2">备案日期：{p.filing_date}</p>}
          {p.note && <p className="mt-2 whitespace-pre-wrap">{p.note}</p>}
        </details>
      </div>

      <IngredientList key={id} ingredients={p.ingredients} cache={ingCache} setCache={setIngCache} />
      <SimilarLevels key={id} productId={id} unit={p.unit_price_unit} />

      <section className="glass-card scroll-mt-24" id="evidence">
        <h2 className="pearl-title">功效证据</h2>
        <EvidenceSummary state={profile} />
        <details className="mt-5">
          <summary className="cursor-pointer text-sm text-pearl-ink">功效宣称依据（{p.claims.length} 条）</summary>
          {p.claims.length === 0 ? (
            <p className="text-sm text-pearl-ink-3 mt-3">暂未收录该产品的功效宣称依据摘要，不代表产品未进行评价。</p>
          ) : p.claims.map((c, i) => <ClaimCard key={i} claim={c} nmpaId={p.nmpa_id} anchorId={`claim-${i}`} doses={matchDoses(c.claim, estimates)} />)}
        </details>
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-pearl-ink">浓度与剂量判定（估计）</summary>
          {p.claims.length > 0 && <VerdictBar claims={p.claims} conc={conc} />}
          <ConcentrationPanel conc={conc} />
        </details>
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-pearl-ink">功效指纹与个人匹配详情</summary>
          <FingerprintBars fp={fp} />
          <MatchScore product={p} conc={conc} fp={fp} />
        </details>
      </section>
    </div>
  )
}
