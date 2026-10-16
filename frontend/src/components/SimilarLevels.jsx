import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading } from './common'
import PriceInfo from './PriceInfo'

function IngredientLinks({ label, items = [] }) {
  return (
    <div className="mt-2 text-xs leading-relaxed">
      <span className="text-pearl-ink-3">{label}：</span>
      {items.length ? items.map((ing, index) => (
        <span key={ing.ingredient_id}>
          {index > 0 && '、'}
          <Link className="text-iris hover:underline" to={`/ingredients/${ing.ingredient_id}`}>{ing.cn_name || ing.inci_name}</Link>
        </span>
      )) : '无'}
    </div>
  )
}

function Candidate({ item, productId, rank, scoreLabel }) {
  return (
    <li className="fairy-panel p-4" data-similar-product={item.id}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="font-num text-rosewood font-semibold">{rank}</span>
        <div className="flex-1 min-w-0">
          <Link className="text-sm font-semibold text-pearl-ink hover:underline break-words" to={`/products/${item.id}`}>{item.name}</Link>
          <div className="text-xs text-pearl-ink-3 mt-1">{item.brand}</div>
          <div className="text-xs text-pearl-ink-2 mt-2">
            {scoreLabel} <b className="font-num">{(item.score * 100).toFixed(1)}%</b>
            {item.shared != null && ` · 共有 ${item.shared} 种 / 并集 ${item.union} 种`}
          </div>
        </div>
        <PriceInfo product={item} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 mt-3">
        <Link to={`/compare?a=${productId}&b=${item.id}`} className="pearl-badge-iris hover:underline">对比这两款 →</Link>
        {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="text-xs text-pearl-ink-3 hover:underline">成分来源 ↗</a>}
      </div>
      {item.shared_ingredients && (
        <details className="mt-3 text-pearl-ink-2">
          <summary className="text-xs cursor-pointer">查看共有与差异成分</summary>
          <IngredientLinks label="共有成分" items={item.shared_ingredients} />
          <IngredientLinks label="仅当前产品含有" items={item.only_target_ingredients} />
          <IngredientLinks label="仅该候选含有" items={item.only_candidate_ingredients} />
        </details>
      )}
    </li>
  )
}

export default function SimilarLevels({ productId, unit }) {
  const [mode, setMode] = useState('ingredients')
  const [sort, setSort] = useState('similarity')
  const [showAll, setShowAll] = useState(false)
  const levels = useFetch(() => api.productSimilarLevels(productId, { k: 20 }), [productId])
  const embedding = useFetch(
    () => mode === 'embedding' ? api.productSimilar(productId, { k: 20 }) : Promise.resolve(null),
    [productId, mode],
  )
  const active = mode === 'embedding' ? embedding : levels
  const items = mode === 'embedding' ? embedding.data?.similar : levels.data?.l1
  const sorted = [...(items || [])].sort((a, b) => {
    const value = (p) => sort === 'unit'
      ? (p.unit_price_unit === unit ? p.unit_price : null) : p.price_current
    if (sort !== 'similarity') {
      const av = value(a), bv = value(b)
      if (av == null && bv != null) return 1
      if (av != null && bv == null) return -1
      if (av != null && bv != null && av !== bv) return av - bv
    }
    return b.score - a.score || a.id - b.id
  })

  return (
    <section className="glass-card scroll-mt-24" aria-label="相似产品与价格" id="similar-products">
      <h2 className="pearl-title">相似产品与价格</h2>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex flex-wrap gap-2">
          {[['ingredients', '成分重合'], ['embedding', '嵌入相似']].map(([value, label]) => (
            <button type="button" key={value} aria-pressed={mode === value} onClick={() => { setMode(value); setShowAll(false) }}
              className={mode === value ? 'fairy-chip !bg-rosewood !text-white' : 'fairy-chip'}>{label}</button>
          ))}
        </div>
        <label className="text-xs text-pearl-ink-2 flex items-center gap-2">
          排序
          <select aria-label="相似产品排序" className="input !w-auto" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="similarity">相似度高到低</option>
            <option value="price">整件参考价低到高</option>
            <option value="unit" disabled={!unit}>同单位单价低到高{unit ? `（元/${unit}）` : ''}</option>
          </select>
        </label>
      </div>
      <p className="text-xs text-pearl-ink-3 mb-4 leading-relaxed">
        {mode === 'embedding' ? '按成分表文本向量检索，百分比为余弦相似度。' : '重合度 = 共有成分数 ÷ 并集成分数。'}
        相似不代表功效等同。价格独立展示，仅重排本次召回的至多 20 款；缺价排后，元/g 与元/ml 分开比较。
      </p>
      {active.loading ? <Loading /> : active.error ? (
        <p className="pearl-notice">相似产品加载失败，请稍后重试。</p>
      ) : items == null ? (
        <p className="pearl-notice">{active.data?.reason || '相似索引暂不可用'}</p>
      ) : !sorted.length ? <p className="text-sm text-pearl-ink-3">暂无可比对的产品</p> : (
        <ol className="space-y-3">{(showAll ? sorted : sorted.slice(0, 5)).map((item, i) => (
          <Candidate key={item.id} item={item} rank={i + 1} productId={productId} scoreLabel={mode === 'embedding' ? '嵌入相似度' : '成分重合度'} />
        ))}</ol>
      )}
      {sorted.length > 5 && !active.loading && !active.error && <button type="button" className="btn-fairy-ghost w-full mt-3" onClick={() => setShowAll(!showAll)}>{showAll ? '收起候选' : `展开全部 ${sorted.length} 款候选`}</button>}
      <details className="mt-5 border-t border-line pt-3">
        <summary className="cursor-pointer text-xs text-pearl-ink-2">更多比较：剂量与功效指纹</summary>
        <p className="text-xs text-pearl-ink-3 my-3">剂量为浓度估计；功效指纹为证据统计信号，均不代表实际效果。</p>
        {levels.loading ? <Loading /> : levels.error ? <p className="text-xs">数据暂不可用</p> : (
          <div className="grid md:grid-cols-2 gap-4">
            <div><h3 className="text-sm font-semibold mb-2">剂量级相似（估计）</h3>
              {!levels.data?.l2.available ? <p className="text-xs text-pearl-ink-3">{levels.data?.l2.reason}</p>
                : <ol className="space-y-2">{levels.data.l2.similar.map((item, i) => <Candidate key={item.id} item={item} rank={i + 1} productId={productId} scoreLabel="剂量相似度（估计）" />)}</ol>}
            </div>
            <div><h3 className="text-sm font-semibold mb-2">功效指纹相似（证据统计）</h3>
              {!levels.data?.l3.length ? <p className="text-xs text-pearl-ink-3">暂无可比对的功效指纹</p>
                : <ol className="space-y-2">{levels.data.l3.map((item, i) => <Candidate key={item.id} item={item} rank={i + 1} productId={productId} scoreLabel="功效指纹相似度" />)}</ol>}
            </div>
          </div>
        )}
      </details>
    </section>
  )
}
