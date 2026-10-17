import { LEVELS, TYPES, ingredientName } from './labels.mjs'

function ProductContributions({ side, state, family, onSource }) {
  const d = state.data?.dimensions.find(row => row.canonical === family)
  return <div className="cap-contributor-product" data-testid={`contributions-${side}`}>
    <h4><span className={`cap-badge cap-badge-${side}`}>产品 {side}</span> {d ? `${d.ingredient_count} 个成分 · ${d.source_count} 个来源` : ''}</h4>
    {state.loading ? <p className="cap-muted">资料加载中…</p> : state.error ? <p className="cap-muted">该产品资料暂未加载。</p> : !d?.contributions.length ? <p className="cap-muted">{d?.status === 'unrated' ? '资料尚未明确评级，未计入指数。' : '暂无可计入该方向的成分证据。'}</p> : <>
      {d.contributions.slice(0, 3).map(c => <Contribution key={c.ingredient_id} item={c} side={side} family={family} onSource={onSource} />)}
      {d.contributions.length > 3 && <details className="cap-more"><summary>展开其余 {d.contributions.length - 3} 个成分</summary>
        {d.contributions.slice(3).map(c => <Contribution key={c.ingredient_id} item={c} side={side} family={family} onSource={onSource} />)}
      </details>}
      <p className="cap-dose-coverage">可作浓度对照：{d.dose_coverage.assessable}/{d.dose_coverage.total} 个贡献成分</p>
    </>}
  </div>
}

function Contribution({ item: c, side, family, onSource }) {
  return <article className="cap-contribution">
    <div className="cap-contribution-heading"><span>{ingredientName(c)}</span><strong title="该成分计入指数的证据权重">+{c.weight.toFixed(2)}</strong></div>
    <p className="cap-evidence-kind">{c.reference_only ? TYPES.book : LEVELS[c.evidence_level] || '未明确分级'}</p>
    <p className="cap-concentration">{c.concentration.label}{!c.dose.research_available && ' · 研究浓度缺失'}</p>
    <div className="cap-source-actions"><button type="button" className="cap-text-button" onClick={() => onSource({ ingredientId: c.ingredient_id, contribution: c, family, side })}>查看来源</button>
      {c.evidence.url && <a href={c.evidence.url} target="_blank" rel="noreferrer" aria-label={`打开${c.evidence.title}原文`}>原文 ↗</a>}
    </div>
  </article>
}

export default function Contributions({ a, b, family, onSource }) {
  return <aside className="cap-contributions" aria-label={`${family}的成分依据`}>
    <div className="cap-detail-heading"><p className="cap-eyebrow">从指数追到成分与来源</p><h3>{family}的依据</h3><p>每个数值，都能查看计入的资料。</p></div>
    <div className="cap-contributor-columns" key={`${a.data?.product_id}-${b.data?.product_id}-${family}`}>
      <ProductContributions side="A" state={a} family={family} onSource={onSource} />
      <ProductContributions side="B" state={b} family={family} onSource={onSource} />
    </div>
    <details className="cap-exclusions" key={`excluded-${family}`}><summary>未计入的资料与原因</summary>
      {[[a, 'A'], [b, 'B']].map(([state, side]) => <div key={side}><h4>产品 {side}</h4>
        {!(state.data?.excluded || []).filter(c => c.canonical === family).length && <p>本方向暂无可展开的排除记录。</p>}
        {(state.data?.excluded || []).filter(c => c.canonical === family).map(c => <article key={c.assertion_id}><p>{ingredientName(c)} · {c.reason}</p>
          <button type="button" className="cap-text-button" onClick={() => onSource({ ingredientId: c.ingredient_id, contribution: c, family, side, excluded: true })}>{c.evidence.title}</button></article>)}
      </div>)}
    </details>
  </aside>
}
