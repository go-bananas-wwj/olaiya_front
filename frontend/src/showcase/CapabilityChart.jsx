import { chartScale } from './logic.mjs'
import { DIRECTIONS } from './labels.mjs'

export default function CapabilityChart({ a, b, aId, bId, family, onFamily }) {
  const scale = chartScale([a.data, b.data])
  const versionsMatch = !a.data || !b.data || a.data.method_version === b.data.method_version
  return <section className="cap-chart-panel" aria-label="成分功效证据指数对照">
    <div className="cap-chart-title"><div><p className="cap-eyebrow">成分功效证据指数</p><h2>哪些功效方向，有更多成分证据支持？</h2></div></div>
    <div className="cap-chart-meta"><span><b className="cap-key cap-key-A">A</b> 产品 A</span><span><b className="cap-key cap-key-B">B</b> 产品 B</span><span>点击功效查看依据 →</span></div>
    <div className="cap-coverage">
      {[[a, 'A', aId], [b, 'B', bId]].map(([state, side, id]) => <div key={side} data-testid={`profile-${side}`} data-loaded={Boolean(state.data)} data-product-id={id}>
        {state.loading ? `${side} 的指数加载中…` : state.error ? <span role="alert">{side} 的指数加载失败：{state.error}</span>
          : `${side}：计入 ${state.data.coverage.ingredients_scored}/${state.data.coverage.ingredients_total} 个成分`}
      </div>)}
    </div>
    {!versionsMatch && <p role="alert">计算方法版本不同，暂不进行数值对照。</p>}
    <div data-testid="capability-chart" data-scale={scale} className="cap-chart">
      <div className="cap-axis" aria-label={`统一刻度，0 至 ${scale}`}><span>统一刻度</span><span>0</span><span>{(scale / 2).toFixed(2)}</span><span>{scale.toFixed(2)}</span></div>
      {DIRECTIONS.map(canonical => <button type="button" className={`cap-chart-row ${family === canonical ? 'is-active' : ''}`} key={canonical}
        aria-label={`查看${canonical}依据`} aria-pressed={family === canonical} onClick={() => onFamily(canonical)}>
        <span className="cap-family-name">{canonical}</span>
        <span className="cap-bars">{[[a, 'A'], [b, 'B']].map(([state, side]) => {
          const d = state.data?.dimensions.find(row => row.canonical === canonical)
          const known = versionsMatch && d?.score != null && Number.isFinite(d.score)
          const status = state.loading ? '加载中' : state.error ? '加载失败' : !versionsMatch ? '版本不可比' : d?.status === 'unrated' ? '未明确评级' : '资料不足'
          return <span className="cap-meter" key={side} aria-label={`${side} ${canonical}：${known ? `证据指数 ${d.score}，${d.ingredient_count} 个成分` : status}`}>
            <span className={`cap-meter-label cap-color-${side}`}>{side}</span>
            <span className="cap-track"><span className={`cap-fill cap-fill-${side}`} data-testid={`bar-${side}-${canonical}`} data-score={known ? d.score : ''} style={{ width: known ? `${d.score / scale * 100}%` : '0%' }} /></span>
            <span className={`cap-meter-value ${known ? '' : 'cap-muted'}`}>{known ? d.score.toFixed(2) : status}</span>
            <span className="cap-meter-count">{known ? `${d.ingredient_count} 成分` : ''}</span>
          </span>
        })}</span>
      </button>)}
    </div>
    <p className="cap-index-note">指数汇总已收录的成分证据，受资料覆盖影响，不是成品实测效果。</p>
    <details className="cap-method"><summary>指数怎么算？哪些资料不计入？</summary>
      <p>每个成分在同一功效方向取最高合格证据权重，再按成分相加。研究来源按证据 ID 去重计数。浓度资料单独展示，不乘入默认剂量系数。</p>
      <p>合格论文与低强度工具书资料可计入；功能分类、法规、安全、供应商、专利、白皮书、口服研究及未评级论文不计入主指数。体外、动物、综述等间接证据保留研究场景和局限。</p>
      <p>没有合格资料显示“资料不足”；未评级单列，真实零值保留 0。数值不代表有效率、综合质量或功效强弱。方法版本：evidence-index-v1。</p>
      <p>A 已排除 {a.data?.excluded.length ?? '—'} 条记录；B 已排除 {b.data?.excluded.length ?? '—'} 条记录。具体排除原因可在右侧“未计入的资料”查看。</p>
    </details>
  </section>
}
