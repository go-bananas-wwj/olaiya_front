import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

export default function ProductPicker({ side, productId, state, onSelect, onSimilar }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState({ items: [] })
  const [active, setActive] = useState(0)
  const box = useRef(null)
  useEffect(() => {
    let current = true
    setResult({ items: [], loading: Boolean(query.trim()) })
    setActive(0)
    const timer = setTimeout(() => {
      if (!query.trim()) return
      api.products({ q: query.trim(), limit: 8 }).then(r => {
        if (current) setResult({ items: r.items || r })
      }).catch(error => { if (current) setResult({ items: [], error: error.message }) })
    }, 220)
    return () => { current = false; clearTimeout(timer) }
  }, [query])
  useEffect(() => { setQuery(''); setOpen(false) }, [productId])
  useEffect(() => {
    const dismiss = e => { if (!box.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [])
  function choose(product) { setOpen(false); setQuery(''); onSelect(product.id) }
  const product = state.data
  return <section className={`cap-product cap-${side}`} data-testid={side === 'A' ? 'target-product' : 'candidate-product'}>
    <div className="cap-product-top"><span className={`cap-badge cap-badge-${side}`}>产品 {side}</span>
      {onSimilar && <button className="cap-text-button" type="button" onClick={onSimilar}>找相似产品</button>}
    </div>
    <div className="cap-search" ref={box}>
      <input role="combobox" aria-label={`搜索产品 ${side}`} aria-autocomplete="list" aria-controls={`results-${side}`} aria-expanded={open && Boolean(query.trim())}
        aria-activedescendant={open && result.items[active] ? `option-${side}-${active}` : undefined}
        value={query} onChange={e => { setQuery(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)}
        placeholder="输入产品名或品牌，替换产品" autoComplete="off"
        onKeyDown={e => {
          if (e.key === 'Escape') setOpen(false)
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive(n => Math.min(n + 1, result.items.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive(n => Math.max(0, n - 1)) }
          if (e.key === 'Enter' && !e.nativeEvent.isComposing && open && result.items[active]) { e.preventDefault(); choose(result.items[active]) }
        }} />
      {open && query.trim() && <div className="cap-search-results" id={`results-${side}`} role="listbox" aria-label={`产品 ${side} 搜索结果`}>
        {result.loading && <p role="status">搜索中…</p>}
        {result.error && <p role="alert">搜索失败：{result.error}</p>}
        {!result.loading && !result.error && !result.items.length && <p>未找到产品，请换个关键词。</p>}
        {result.items.map((p, i) => <button type="button" role="option" aria-selected={active === i} aria-label={`选择 ${p.name}`} id={`option-${side}-${i}`} key={p.id} onClick={() => choose(p)}>
          <small>{p.brand}</small><span>{p.name}</span>
        </button>)}
      </div>}
    </div>
    {state.loading ? <p className="cap-muted" role="status">正在读取产品…</p> : state.error ? <p role="alert">产品加载失败：{state.error}</p> : <>
      <p className="cap-brand">{product.brand}</p>
      <h2 className="cap-product-name" title={product.name}>{product.name}</h2>
      <p className="cap-product-price">{product.price_current == null ? '暂无价格' : `参考价 ¥${Number(product.price_current).toFixed(2)}`}{product.spec && <span> / {product.spec}</span>}</p>
      <details className="cap-product-details"><summary>完整名称与来源</summary><p>{product.name}</p>
        {product.source_url ? <a href={product.source_url} target="_blank" rel="noreferrer">产品与成分来源 ↗</a> : <p>来源链接未记录</p>}
        {product.note && <p>{product.note}</p>}
      </details>
    </>}
  </section>
}
