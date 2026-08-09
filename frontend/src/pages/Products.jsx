import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Loading, LoadError, Empty } from '../components/common'
import ProductCard from '../components/ProductCard'

const PAGE_SIZE = 24 // 每页产品数（加载更多分页）

export default function Products() {
  const [q, setQ] = useState('')
  const [brand, setBrand] = useState('')
  const [hasClaims, setHasClaims] = useState('')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [state, setState] = useState({ loading: true, error: null })
  const [brands, setBrands] = useState([])

  // 品牌下拉：轻量接口，不再拉全量产品提取
  useEffect(() => {
    api.brands().then(setBrands).catch(() => {})
  }, [])

  const fetchPage = (offset) => {
    setState((s) => ({ ...s, loading: true, error: null }))
    return api.products({ q, brand, has_claims: hasClaims, limit: PAGE_SIZE, offset })
      .then(({ total: t, items: page }) => {
        setTotal(t)
        setItems((prev) => (offset === 0 ? page : [...prev, ...page]))
        setState({ loading: false, error: null })
      })
      .catch((e) => setState({ loading: false, error: e.message }))
  }

  useEffect(() => {
    let alive = true
    const timer = setTimeout(() => { if (alive) fetchPage(0) }, 250)
    return () => { alive = false; clearTimeout(timer) }
  }, [q, brand, hasClaims])

  const claimFilters = useMemo(() => [
    ['', '全部'],
    ['true', '有宣称依据'],
    ['false', '无宣称摘要'],
  ], [])

  return (
    <div>
      <div className="card">
        <div className="flex flex-col md:flex-row gap-3">
          <input
            className="input md:flex-1"
            placeholder="搜索产品名 / 品牌…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select className="input md:w-56" value={brand} onChange={(e) => setBrand(e.target.value)}>
            <option value="">全部品牌</option>
            {brands.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <div className="flex gap-1 bg-bg rounded-[10px] p-1 self-start">
            {claimFilters.map(([v, label]) => (
              <button
                key={v}
                onClick={() => setHasClaims(v)}
                className={`btn-page whitespace-nowrap ${hasClaims === v ? 'btn-page-active' : ''}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {state.loading && items.length === 0 && <div className="card"><Loading /></div>}
      {state.error && <div className="card"><LoadError error={state.error} /></div>}
      {!state.loading && !state.error && items.length === 0 && (
        <Empty text="没有匹配的产品，换个关键词或放宽过滤条件试试" />
      )}
      {items.length > 0 && (
        <>
          <div className="text-xs text-ink-3 mb-3">共 {total} 款产品</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((p) => <ProductCard key={p.id} p={p} />)}
          </div>
          {items.length < total && (
            <div className="text-center mt-5">
              <button
                className="btn-page"
                disabled={state.loading}
                onClick={() => fetchPage(items.length)}
              >
                {state.loading ? '加载中…' : `加载更多（已显示 ${items.length} / ${total}）`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
