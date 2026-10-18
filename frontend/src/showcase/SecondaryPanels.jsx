import { useState } from 'react'
import { Drop, SquaresFour, List, ArrowSquareOut } from '@phosphor-icons/react'
import PriceInfo from '../components/PriceInfo'
import { compareIngredients, comparableUnitPrices } from './logic.mjs'
import { ingredientName } from './labels.mjs'
import { SectionHeading } from './ReferencePrimitives'

const ordered = items => [...new Map(items.map(i => [i.ingredient_id, i])).values()]
  .sort((a, b) => (a.position ?? Infinity) - (b.position ?? Infinity))

function IngredientColumn({ side, items, shared, filter, expanded, onExpand, onIngredient }) {
  const filtered = filter === 'differences' ? items.filter(i => !shared.has(i.ingredient_id)) : items
  return <div className="ss-ingredient-column" aria-label={`产品 ${side} 成分表`}>
    {!(filtered.length) && <p className="ss-empty">此视图暂无列出的成分。</p>}
    {(expanded ? filtered : filtered.slice(0, 5)).map(i => <button type="button" className={`ss-ingredient ${filter === 'shared' && shared.has(i.ingredient_id) ? 'is-shared' : ''}`}
      data-shared={shared.has(i.ingredient_id)} key={i.ingredient_id} onClick={() => onIngredient({ ingredientId: i.ingredient_id })}>
      <Drop size={17} weight="fill" aria-hidden="true" />
      <span><strong>{ingredientName(i)}</strong><small>{i.purpose || '用途资料未收录'}</small><small>{i.position == null ? '未知位次' : `来源位次 #${i.position}`}</small></span>
    </button>)}
    {!expanded && filtered.length > 5 && <button type="button" className="ss-expand" onClick={onExpand}>展开全部 {filtered.length} 项</button>}
  </div>
}

export default function SecondaryPanels({ a, b, onIngredient }) {
  const [filter, setFilter] = useState('shared')
  const [view, setView] = useState('list')
  const [expanded, setExpanded] = useState({ A: false, B: false })
  if (!a || !b) return <>
    <section id="ingredients" className="ss-block"><SectionHeading title="成分对照" a={a} b={b} /><p className="ss-empty">产品成分资料尚未就绪，可继续查看已加载的证据。</p></section>
    <section id="price" className="ss-block"><SectionHeading title="参考价格" a={a} b={b} /><p className="ss-empty">产品资料尚未就绪。</p></section>
    <section id="explained" className="ss-block"><SectionHeading title="成分解释" a={a} b={b} /><p className="ss-empty">产品资料尚未就绪。</p></section>
  </>
  const difference = compareIngredients(a.ingredients, b.ingredients)
  const shared = new Set(difference.shared.map(i => i.ingredient_id))
  const comparable = comparableUnitPrices(a, b)
  const priceMax = comparable ? Math.max(1, a.unit_price, b.unit_price) : 1
  return <>
    <section id="ingredients" className="ss-block" aria-label="成分差异" data-view={view}>
      <SectionHeading title="成分对照" a={a} b={b} />
      <div className="ss-view-switch" role="group" aria-label="成分列表样式">
        <button type="button" aria-label="列表视图" aria-pressed={view === 'list'} onClick={() => setView('list')}><List size={13} /> 列表</button>
        <button type="button" aria-label="紧凑视图" aria-pressed={view === 'condensed'} onClick={() => setView('condensed')}><SquaresFour size={13} /> 紧凑</button>
      </div>
      <div className="ss-highlight-controls" role="group" aria-label="成分显示范围"><span>显示方式</span>
        <button type="button" aria-pressed={filter === 'shared'} onClick={() => { setFilter('shared'); setExpanded({ A:false, B:false }) }}>高亮共享成分 ({shared.size})</button>
        <button type="button" aria-pressed={filter === 'differences'} onClick={() => { setFilter('differences'); setExpanded({ A:false, B:false }) }}>只看差异</button>
        <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>全部成分</button>
      </div>
      <p className="ss-section-note">共有 {shared.size} 项 · 仅 A 列出 {difference.onlyTarget.length} 项 · 仅 B 列出 {difference.onlyCandidate.length} 项</p>
      <div className="ss-two-columns ss-ingredient-lists">{[[a, 'A'], [b, 'B']].map(([product, side]) => <IngredientColumn key={side} side={side} items={ordered(product.ingredients)}
        shared={shared} filter={filter} expanded={expanded[side]} onExpand={() => setExpanded(e => ({ ...e, [side]: true }))} onIngredient={onIngredient} />)}</div>
      <p className="ss-section-note">浅绿色表示两款均列出。用途按来源记录，非功效实证；未知位次不推断顺序或浓度。“未列出”不等于实际不含有。</p>
    </section>
    <section id="price" className="ss-block" aria-label="参考价格对照">
      <SectionHeading title="参考价格" a={a} b={b} />
      <p className="ss-section-note">{comparable ? `按同单位比较 · 元/${a.unit_price_unit}` : '价格或可比规格不足，暂不计算单价差异；ml 与 g 不互换。'}</p>
      <div className="ss-two-columns ss-price-columns">{[[a, 'A'], [b, 'B']].map(([product, side]) => <div key={side}>
        {comparable && <div className="ss-unit-price"><strong>{product.unit_price.toFixed(2)}</strong><span>元/{product.unit_price_unit}</span>
          <div className="ss-score-track"><span style={{ width: `${product.unit_price / priceMax * 100}%` }} /></div>
        </div>}
        <PriceInfo product={product} />
      </div>)}</div>
      <p className="ss-section-note">历史参考价格，非实时售价。价格与证据指数分别展示。</p>
    </section>
    <section id="explained" className="ss-block" aria-label="共享成分解释">
      <SectionHeading title="成分解释" a={a} b={b} />
      <p className="ss-section-note">以下成分在两款产品中均有记录。点击查看本库收录的研究、分类与限制。</p>
      <div className="ss-explained-list">{difference.shared.slice(0, 3).map(i => <article key={i.ingredient_id}>
        <h3><Drop size={17} weight="duotone" /> {ingredientName(i)}</h3><p className="ss-inci">{i.inci_name}</p>
        <p>{i.purpose ? `来源记录的用途：${i.purpose}` : '暂未收录该成分的用途说明；可展开查看相关资料与来源。'}</p>
        <button type="button" className="ss-read-more" onClick={() => onIngredient({ ingredientId: i.ingredient_id })}>查看成分资料 <ArrowSquareOut size={12} /></button>
      </article>)}</div>
      {!difference.shared.length && <p className="ss-empty">当前两款产品暂无共同列出的成分。</p>}
    </section>
  </>
}
