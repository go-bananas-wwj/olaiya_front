import { Drop, Sparkle, Leaf, ShieldCheck, Sun, TestTube, ArrowRight } from '@phosphor-icons/react'
import { chartScale } from './logic.mjs'
import { DIRECTIONS } from './labels.mjs'
const ICONS={保湿:Drop,抗皱:Sparkle,修护:ShieldCheck,舒缓:Leaf,抗氧化:Sun,美白:Sparkle,控油祛痘:TestTube,焕肤:Leaf}

export default function CapabilityChart({a,b,aId,bId,family,onFamily}) {
 const scale=chartScale([a.data,b.data])
 const same=!a.data||!b.data||a.data.method_version===b.data.method_version
 return <section id="benefits" className="comparison-chart" aria-label="成分功效证据指数对照">
  <div className="comparison-chart-heading"><h2>八个方向，逐项对照</h2><span>点击方向，查看成分依据 <ArrowRight size={13}/></span></div>
  <div className="comparison-coverage">{[[a,'A',aId],[b,'B',bId]].map(([state,side,id])=><span key={side} data-testid={`profile-${side}`} data-loaded={Boolean(state.data)} data-product-id={id}>{state.loading?`${side} 的指数加载中…`:state.error?<span role="alert">{side} 的指数加载失败：{state.error}</span>:<><b className={`comparison-letter ${side}`}>{side}</b>计入 {state.data.coverage.ingredients_scored} / {state.data.coverage.ingredients_total} 个成分</>}</span>)}</div>
  {!same&&<p role="alert">计算方法版本不同，暂不进行数值对照。</p>}
  <div data-testid="capability-chart" data-scale={scale} className="comparison-rows">
  {DIRECTIONS.map(canonical=>{const Icon=ICONS[canonical];return <button type="button" key={canonical} className={`comparison-row ${family===canonical?'is-selected':''}`} aria-label={`查看${canonical}依据`} aria-pressed={family===canonical} onClick={()=>onFamily(canonical)}>
   <span className="comparison-direction"><Icon size={16} weight="duotone" aria-hidden="true"/>{canonical}</span>
   {[[a,'A'],[b,'B']].map(([state,side])=>{const d=state.data?.dimensions.find(d=>d.canonical===canonical),known=same&&Number.isFinite(d?.score)
    const unknown=state.loading?'加载中':state.error?'加载失败':!same?'版本不可比':d?.status==='unrated'?'未明确评级':'资料不足'
    return <span key={side} className={`comparison-value ${side}`} aria-label={`${side} ${canonical}：${known?`指数${d.score}，${d.ingredient_count}成分，${d.source_count}来源`:unknown}`}>
      <span className="comparison-side-letter">{side}</span><span className="comparison-track"><span data-testid={`bar-${side}-${canonical}`} data-score={known?d.score:''} style={{width:known?`${d.score/scale*100}%`:'0%'}}/></span><strong>{known?d.score.toFixed(2):unknown}</strong>
    </span>
   })}
  </button>})}</div>
  <p className="comparison-index-note">成分功效证据指数 · 共用刻度 0–{scale.toFixed(2)}。汇总已收录资料，不是成品实测效果；资料不足不补零。</p>
  <details className="ss-method" id="method"><summary>指数方法与未计入的资料</summary><p>沿用 evidence-index-v1，同成分同方向取最高合格证据权重后相加；来源按证据ID去重，浓度单列。合格论文与低强度工具书可计入；功能分类、法规、安全、供应商、专利、白皮书、口服和未评级论文不计入主指数。</p><p>间接与复方研究保留场景限制，不视为单一成分的独立临床效果。A 已排除 {a.data?.excluded.length??'—'} 条，B 已排除 {b.data?.excluded.length??'—'} 条；具体记录在贡献成分区展开。</p></details>
 </section>
}
