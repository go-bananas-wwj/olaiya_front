import { useState } from 'react'
import { Drop, Sparkle, Leaf, ShieldCheck, Sun, TestTube, CaretDown } from '@phosphor-icons/react'
import { chartScale } from './logic.mjs'
import { DIRECTIONS } from './labels.mjs'
import { SectionHeading } from './ReferencePrimitives'

const ICONS = { 保湿: Drop, 抗皱: Sparkle, 修护: ShieldCheck, 舒缓: Leaf, 抗氧化: Sun, 美白: Sparkle, 控油祛痘: TestTube, 焕肤: Leaf }

export default function CapabilityChart({ a, b, aId, bId, productA, productB, family, onFamily }) {
  const [expanded, setExpanded] = useState(false)
  const scale = chartScale([a.data, b.data])
  const versionsMatch = !a.data || !b.data || a.data.method_version === b.data.method_version
  return <section id="benefits" className="ss-block" aria-label="成分功效证据指数对照">
    <SectionHeading title="功效证据" a={productA} b={productB} />
    <p className="ss-section-note">数值为成分功效证据指数。点击一个方向，查看贡献成分与来源。</p>
    <div className="ss-coverage ss-two-columns">
      {[[a, 'A', aId], [b, 'B', bId]].map(([state, side, id]) => <div key={side} data-testid={`profile-${side}`} data-loaded={Boolean(state.data)} data-product-id={id}>
        {state.loading ? `${side} 的指数加载中…` : state.error ? <span role="alert">{side} 的指数加载失败：{state.error}</span>
          : `计入 ${state.data.coverage.ingredients_scored} / ${state.data.coverage.ingredients_total} 个成分`}
      </div>)}
    </div>
    {!versionsMatch && <p role="alert" className="ss-section-note">计算方法版本不同，暂不进行数值对照。</p>}
    <div data-testid="capability-chart" data-scale={scale} className="ss-benefits">
      {(expanded ? DIRECTIONS : DIRECTIONS.slice(0, 4)).map(canonical => {
        const Icon = ICONS[canonical]
        return <button type="button" className={`ss-benefit-pair ss-two-columns ${family === canonical ? 'is-selected' : ''}`} key={canonical}
          aria-label={`查看${canonical}依据`} aria-pressed={family === canonical} onClick={() => onFamily(canonical)}>
          {[[a, 'A'], [b, 'B']].map(([state, side]) => {
            const d = state.data?.dimensions.find(row => row.canonical === canonical)
            const known = versionsMatch && d?.score != null && Number.isFinite(d.score)
            const status = state.loading ? '加载中' : state.error ? '加载失败' : !versionsMatch ? '版本不可比' : d?.status === 'unrated' ? '未明确评级' : '资料不足'
            return <span className="ss-benefit-cell" key={side} aria-label={`${side} ${canonical}：${known ? `证据指数 ${d.score}，${d.ingredient_count} 个成分` : status}`}>
              <span className={`ss-benefit-icon ${known ? '' : 'is-unknown'}`}><Icon size={18} weight="duotone" aria-hidden="true" /></span>
              <span className="ss-benefit-copy"><strong>{canonical}</strong><small>{known ? `${d.ingredient_count} 个贡献成分 · ${d.source_count} 个来源` : status}</small>
                <span className="ss-score-track"><span data-testid={`bar-${side}-${canonical}`} data-score={known ? d.score : ''} style={{ width: known ? `${d.score / scale * 100}%` : '0%' }} /></span>
              </span>
              <span className="ss-benefit-score">{known ? d.score.toFixed(2) : '—'}</span>
            </span>
          })}
        </button>
      })}
    </div>
    {!expanded && <button type="button" className="ss-expand" onClick={() => setExpanded(true)}>展开全部 8 项功效 <CaretDown size={13} aria-hidden="true" /></button>}
    <p className="ss-section-note">统一刻度 0–{scale.toFixed(2)}。指数受资料覆盖影响，不是成品实测效果或有效率。</p>
    <details className="ss-method" id="method"><summary>指数方法与未计入的资料</summary>
      <p>同一成分、同一功效取最高合格证据权重，再按成分相加。来源按证据 ID 去重计数，浓度单独呈现，不乘入默认剂量系数。</p>
      <p>合格论文与低强度工具书可计入；功能分类、法规、安全、供应商、专利、白皮书、口服与未评级论文不计入主指数。间接或复方资料保留研究条件和局限。</p>
      <p>没有合格资料显示“资料不足”，未评级单列；真实零值保留 0。方法版本 evidence-index-v1。A 已排除 {a.data?.excluded.length ?? '—'} 条，B 已排除 {b.data?.excluded.length ?? '—'} 条；具体记录在贡献成分区展开。</p>
    </details>
  </section>
}
