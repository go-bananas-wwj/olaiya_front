import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Loading, LoadError } from '../components/common'
import ProductCard from '../components/ProductCard'

const PAGE_SIZE = 24 // 每页产品数（加载更多分页）
// 功效胶囊：与后端 EFFICACY_KEYWORDS 枚举一一对应（宣称文本筛选口径，非成分证据族）
const EFFICACY_CAPS = ['美白', '抗老', '保湿', '祛痘', '舒缓', '防晒']
const SORT_OPTIONS = [
  ['', '默认排序'],
  ['claim_count_desc', '宣称多→少'],
  ['ingredient_count_desc', '成分多→少'],
]

export default function Products() {
  const [searchParams, setSearchParams] = useSearchParams()
  // 工具条状态全量镜像到 URL（q/efficacy/brand/has_claims/sort），可分享、可入站
  const q = searchParams.get('q') || ''
  const efficacy = searchParams.get('efficacy') || ''
  const brand = searchParams.get('brand') || ''
  const hasClaims = searchParams.get('has_claims') === 'true'
  const sort = searchParams.get('sort') || ''

  const [qInput, setQInput] = useState(q) // 搜索框本地态，250ms 防抖回写 URL
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [state, setState] = useState({ loading: true, error: null })
  const [brands, setBrands] = useState([])

  const reqSeq = useRef(0) // 竞态守卫：响应落地前比对最新序号，过期丢弃
  const loadingRef = useRef(false) // 加载更多去重锁：同 offset 不并发

  // 品牌下拉：轻量接口，不再拉全量产品提取
  useEffect(() => {
    api.brands().then(setBrands).catch(() => {})
  }, [])

  // URL 上的 q 变化（入站参数/前进后退/清空筛选）时同步回输入框
  useEffect(() => { setQInput(q) }, [q])

  // 搜索输入 250ms 防抖回写 URL，由 URL 变化驱动查询
  useEffect(() => {
    if (qInput === q) return undefined
    const timer = setTimeout(() => updateParams({ q: qInput }), 250)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qInput])

  // 只写非空参数，保持 URL 干净；函数式更新避免防抖回写覆盖期间变化的其它筛选
  const updateParams = (patch) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v)
        else next.delete(k)
      }
      return next
    })
  }

  const fetchPage = (offset, append) => {
    const seq = ++reqSeq.current
    setState((s) => ({ ...s, loading: true, error: null }))
    return api.products({
      q, efficacy, brand,
      has_claims: hasClaims ? 'true' : '',
      sort, limit: PAGE_SIZE, offset,
    })
      .then(({ total: t, items: page }) => {
        if (seq !== reqSeq.current) return // 过期响应丢弃
        setTotal(t)
        setItems((prev) => (append ? [...prev, ...page] : page))
        setState({ loading: false, error: null })
      })
      .catch((e) => {
        if (seq !== reqSeq.current) return
        setState({ loading: false, error: e.message })
      })
  }

  // 筛选变化：重置 offset 重新查询第一页
  useEffect(() => {
    fetchPage(0, false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, efficacy, brand, hasClaims, sort])

  const loadMore = () => {
    if (loadingRef.current) return
    loadingRef.current = true
    fetchPage(items.length, true).finally(() => { loadingRef.current = false })
  }

  const hasFilter = !!(q || efficacy || brand || hasClaims)
  const clearFilters = () => {
    setQInput('')
    setSearchParams({})
  }

  return (
    <div>
      {/* 粘性玻璃工具条：搜索｜功效胶囊｜品牌｜只看有宣称｜排序 */}
      <div className="sticky top-3 z-20 rounded-[18px] border border-[rgba(138,90,106,0.22)] bg-white/70 backdrop-blur-md shadow-[0_10px_30px_-14px_rgba(61,47,42,0.35)] px-4 py-3 mb-5 space-y-2.5">
        <div className="flex flex-col md:flex-row gap-2.5">
          <input
            className="input md:flex-1 !bg-white/80"
            placeholder="搜产品名 / 品牌 / 备案号…"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
          />
          <select
            className="input md:w-44 !bg-white/80"
            value={brand}
            onChange={(e) => updateParams({ brand: e.target.value })}
          >
            <option value="">全部品牌</option>
            {brands.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <select
            className="input md:w-40 !bg-white/80"
            value={sort}
            onChange={(e) => updateParams({ sort: e.target.value })}
          >
            {SORT_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
          <button
            aria-pressed={hasClaims}
            onClick={() => updateParams({ has_claims: hasClaims ? '' : 'true' })}
            className={`btn-page whitespace-nowrap rounded-full border ${
              hasClaims
                ? 'bg-rosewood/15 text-rosewood border-rosewood/50'
                : 'text-pearl-ink-2 border-line bg-white/60'
            }`}
          >
            {hasClaims ? '✓ 只看有宣称' : '只看有宣称'}
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => updateParams({ efficacy: '' })}
            className={`fairy-chip transition-colors ${
              !efficacy ? '!bg-rosewood !text-white !border-rosewood' : 'hover:bg-rosewood/20'
            }`}
          >
            全部
          </button>
          {EFFICACY_CAPS.map((cap) => (
            <button
              key={cap}
              onClick={() => updateParams({ efficacy: efficacy === cap ? '' : cap })}
              className={`fairy-chip transition-colors ${
                efficacy === cap ? '!bg-rosewood !text-white !border-rosewood' : 'hover:bg-rosewood/20'
              }`}
            >
              {cap}
            </button>
          ))}
        </div>
      </div>

      {state.loading && items.length === 0 && (
        <div className="bg-card rounded-card shadow-card"><Loading /></div>
      )}
      {state.error && <LoadError error={state.error} />}
      {!state.loading && !state.error && items.length === 0 && (
        <div className="bg-card rounded-card shadow-card py-16 px-8 text-center text-ink-3 text-sm">
          {hasFilter ? (
            <>
              <div>没有匹配的产品，换个关键词或放宽筛选试试</div>
              <button className="btn-fairy-ghost !px-5 !py-2 mt-5" onClick={clearFilters}>
                一键清空筛选
              </button>
            </>
          ) : (
            <>
              <div>全库暂无匹配产品</div>
              <Link to="/decode" className="btn-fairy-ghost !px-5 !py-2 mt-5">
                试试解码成分表 →
              </Link>
            </>
          )}
        </div>
      )}
      {items.length > 0 && (
        <>
          <div className="text-xs text-pearl-ink-3 mb-3">
            共 <span className="font-num">{total}</span> 款产品
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((p) => <ProductCard key={p.id} p={p} />)}
          </div>
          {items.length < total && (
            <div className="text-center mt-5">
              <button
                className="btn-fairy-ghost !px-5 !py-2"
                disabled={state.loading}
                onClick={loadMore}
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
