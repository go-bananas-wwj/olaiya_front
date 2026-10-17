import { useState } from 'react'
import PriceInfo from '../components/PriceInfo'
import { compareIngredients, comparableUnitPrices, ingredientRows } from './logic.mjs'
import { ingredientName } from './labels.mjs'

export default function SecondaryPanels({ a, b, onIngredient }) {
  const [view, setView] = useState('differences')
  const [expanded, setExpanded] = useState(false)
  const difference = compareIngredients(a.ingredients, b.ingredients)
  const rows = ingredientRows(a.ingredients, b.ingredients, view)
  const comparable = comparableUnitPrices(a, b)
  const priceMax = comparable ? Math.max(1, a.unit_price, b.unit_price) : 1
  return <div className="cap-secondary">
    <section className="cap-secondary-card" aria-label="成分差异">
      <h2>成分差异</h2>
      <p className="cap-overlap-counts">共有 <b>{difference.shared.length}</b> 项 · 仅 A 列出 <b>{difference.onlyTarget.length}</b> 项 · 仅 B 列出 <b>{difference.onlyCandidate.length}</b> 项</p>
      <div className="cap-view-buttons" role="group" aria-label="成分表视图">{[['differences', '只看差异'], ['shared', '共有成分'], ['all', '完整成分表']].map(([value, label]) =>
        <button type="button" key={value} aria-pressed={view === value} onClick={() => { setView(value); setExpanded(false) }}>{label}</button>)}</div>
      <table className="cap-ingredient-table"><thead><tr><th scope="col">成分</th><th scope="col">产品 A</th><th scope="col">产品 B</th></tr></thead>
        <tbody>{(expanded ? rows : rows.slice(0, 8)).map(row => <tr key={row.ingredient_id}>
          <th scope="row"><button type="button" className="cap-text-button" onClick={() => onIngredient({ ingredientId: row.ingredient_id })}>{ingredientName(row)}</button></th>
          {['a', 'b'].map(side => <td key={side}>{row[side] ? <><span>已列出</span><small>{row[side].position == null ? '未知位次' : `#${row[side].position}`}</small></> : <span className="cap-muted">未列出</span>}</td>)}
        </tr>)}</tbody>
      </table>
      {!rows.length && <p className="cap-muted">此视图暂无列出的成分。</p>}
      {!expanded && rows.length > 8 && <button type="button" className="cap-text-button cap-load-more" onClick={() => setExpanded(true)}>展开其余 {rows.length - 8} 项</button>}
      <p className="cap-small-note">“未列出”仅说明当前成分表中未记录；未知位次不推断顺序或浓度。</p>
    </section>
    <section className="cap-secondary-card" aria-label="参考价格对照">
      <h2>参考价格</h2>
      {comparable ? <div className="cap-price-chart" aria-label={`同单位参考单价，元/${a.unit_price_unit}`}>
        <p className="cap-muted">按同单位比较 · 元/{a.unit_price_unit}</p>
        {[[a, 'A'], [b, 'B']].map(([product, side]) => <div className="cap-price-row" key={side}>
          <span className={`cap-badge cap-badge-${side}`}>{side}</span>
          <div className="cap-track"><span className={`cap-fill cap-fill-${side}`} style={{ width: `${product.unit_price / priceMax * 100}%` }} /></div>
          <strong>{product.unit_price.toFixed(2)}</strong>
        </div>)}
      </div> : <p className="cap-empty-note">价格或可比规格不足，暂不计算单价差异；ml 与 g 不互换。</p>}
      <div className="cap-price-details">{[[a, 'A'], [b, 'B']].map(([product, side]) => <div key={side}><p className={`cap-color-${side}`}>产品 {side}</p><PriceInfo product={product} /></div>)}</div>
      <p className="cap-small-note">参考价格为带来源和记录日期的历史采样，非实时售价。价格与证据指数分别展示。</p>
    </section>
  </div>
}
