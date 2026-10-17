import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { ProductPhoto } from './ReferencePrimitives'
import { MagnifyingGlass, X } from '@phosphor-icons/react'

export default function ProductPicker({ side, productId, state, onSelect }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [result, setResult] = useState({ items: [] })
  const [active, setActive] = useState(0)
  const box = useRef(null)
  const input = useRef(null)
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
  useEffect(() => { setQuery(''); setOpen(false); setEditing(false) }, [productId])
  useEffect(() => { if (editing) input.current?.focus() }, [editing])
  useEffect(() => {
    const dismiss = e => { if (!box.current?.contains(e.target)) { setOpen(false); setEditing(false) } }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [])
  function choose(product) { setOpen(false); setEditing(false); setQuery(''); onSelect(product.id) }
  const product = state.data
  return <section ref={box} className="ss-product" data-testid={side === 'A' ? 'target-product' : 'candidate-product'}>
    <button type="button" className="ss-change-product" aria-label={`更换产品 ${side}`} aria-expanded={editing} onClick={() => setEditing(v => !v)}><MagnifyingGlass size={13} aria-hidden="true" /> 更换产品 {side}</button>
    {editing && <div className="ss-product-search">
      <button className="ss-search-close" type="button" aria-label={`关闭产品 ${side} 搜索`} onClick={() => setEditing(false)}><X size={14} /></button>
      <input ref={input} role="combobox" aria-label={`搜索产品 ${side}`} aria-autocomplete="list" aria-controls={`results-${side}`} aria-expanded={open && Boolean(query.trim())}
        aria-activedescendant={open && result.items[active] ? `option-${side}-${active}` : undefined}
        value={query} onChange={e => { setQuery(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)}
        placeholder="输入产品名或品牌，替换产品" autoComplete="off"
        onKeyDown={e => {
          if (e.key === 'Escape') { setOpen(false); setEditing(false) }
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive(n => Math.min(n + 1, result.items.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive(n => Math.max(0, n - 1)) }
          if (e.key === 'Enter' && !e.nativeEvent.isComposing && open && result.items[active]) { e.preventDefault(); choose(result.items[active]) }
        }} />
      {open && query.trim() && <div className="ss-search-results" id={`results-${side}`} role="listbox" aria-label={`产品 ${side} 搜索结果`}>
        {result.loading && <p role="status">搜索中…</p>}
        {result.error && <p role="alert">搜索失败：{result.error}</p>}
        {!result.loading && !result.error && !result.items.length && <p>未找到产品，请换个关键词。</p>}
        {result.items.map((p, i) => <button type="button" role="option" aria-selected={active === i} aria-label={`选择 ${p.name}`} id={`option-${side}-${i}`} key={p.id} onClick={() => choose(p)}>
          <small>{p.brand}</small><span>{p.name}</span>
        </button>)}
      </div>}
    </div>}
    <div className="ss-product-visual"><ProductPhoto product={product} side={side} /></div>
    {state.loading ? <p className="cap-muted" role="status">正在读取产品…</p> : state.error ? <p role="alert">产品加载失败：{state.error}</p> : <>
      <p className="ss-product-brand">{product.brand}</p>
      <h2 className="ss-product-name" title={product.name}>{product.name}</h2>
      <p className="ss-product-price">{product.price_current == null ? '暂无价格' : `参考价 ¥${Number(product.price_current).toFixed(2)}`}{product.spec && <span> / {product.spec}</span>}</p>
      <details className="ss-product-details"><summary>完整名称与来源</summary><p>{product.name}</p>
        {product.source_url ? <a href={product.source_url} target="_blank" rel="noreferrer">产品与成分来源 ↗</a> : <p>来源链接未记录</p>}
        {product.note && <p>{product.note}</p>}
      </details>
    </>}
  </section>
}
