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

// —— Highlights 配方特征标签（P1）：由成分表规则推出，注明口径 ——
const hlNorm = (s) => (s || '').toUpperCase().replace(/[.\s]/g, '')
const HL_ALCOHOL = new Set(['ALCOHOL', 'ALCOHOLDENAT', 'SDALCOHOL', 'ETHANOL', '变性乙醇', '乙醇'])

function highlights(ingredients) {
  const hasAlcohol = ingredients.some((i) => HL_ALCOHOL.has(hlNorm(i.inci_name)) || HL_ALCOHOL.has(i.cn_name))
  const hasFragrance = ingredients.some((i) =>
    hlNorm(i.inci_name).includes('FRAGRANCE') || hlNorm(i.inci_name).includes('PARFUM') ||
    (i.cn_name || '').includes('香精'))
  const hasPreservative = ingredients.some((i) => (i.purpose || '').includes('防腐'))
  const tags = []
  if (!hasAlcohol) tags.push({ text: '无酒精', cls: 'pearl-badge-ok' })
  if (!hasFragrance) tags.push({ text: '无香精', cls: 'pearl-badge-ok' })
  if (hasPreservative) tags.push({ text: '含防腐剂', cls: 'pearl-badge-warn' })
  return tags
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
  // 浓度数据页面级预取：判决条 / 宣称卡 hero / 浓度区块共用同一份
  const conc = useFetch(() => api.productConcentration(id), [id])
  // 功效指纹页面级预取：指纹条 / 匹配分共用同一份
  const fp = useFetch(() => api.productFingerprint(id), [id])
  // 成分行内展开的档案懒加载缓存（{ [ingredientId]: {status, data} }），换产品时清空
  const [ingCache, setIngCache] = useState({})
  useEffect(() => { setIngCache({}) }, [id])

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
  const hl = highlights(p.ingredients)

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
          {hl.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {hl.map((t) => <span key={t.text} className={t.cls}>{t.text}</span>)}
              <span className="text-xs text-pearl-ink-3">由成分表规则推出</span>
            </div>
          )}
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

        {/* 功效指纹条（置顶宣称核验区上方） */}
        <FingerprintBars fp={fp} />

        {/* 透明匹配分（肤质档案 localStorage，逐项可展开） */}
        <MatchScore product={p} conc={conc} fp={fp} />

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

        <IngredientList ingredients={p.ingredients} cache={ingCache} setCache={setIngCache} />

        <SimilarLevels productId={id} />
      </div>
    </div>
  )
}
