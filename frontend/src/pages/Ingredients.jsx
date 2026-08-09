import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Loading, LoadError, Empty } from '../components/common'

const PAGE_SIZE = 60 // 每页成分数（加载更多分页）

export default function Ingredients() {
  const [q, setQ] = useState('')
  const [onlyEvidence, setOnlyEvidence] = useState(false)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [state, setState] = useState({ loading: true, error: null })

  const fetchPage = (offset) => {
    setState((s) => ({ ...s, loading: true, error: null }))
    return api.ingredients({
      q, has_evidence: onlyEvidence ? 'true' : '', limit: PAGE_SIZE, offset,
    })
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
  }, [q, onlyEvidence])

  return (
    <div>
      <div className="card">
        <div className="flex flex-col md:flex-row gap-3 md:items-center">
          <input
            className="input md:flex-1"
            placeholder="搜索中文名 / INCI 名…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <label className="flex items-center gap-2 text-sm text-ink-2 cursor-pointer select-none self-start">
            <input
              type="checkbox"
              checked={onlyEvidence}
              onChange={(e) => setOnlyEvidence(e.target.checked)}
              className="w-4 h-4 accent-brand"
            />
            只看有文献证据
          </label>
        </div>
      </div>

      {state.loading && items.length === 0 && <div className="card"><Loading /></div>}
      {state.error && <div className="card"><LoadError error={state.error} /></div>}
      {!state.loading && !state.error && items.length === 0 && <Empty text="没有匹配的成分" />}
      {items.length > 0 && (
        <>
          <div className="text-xs text-ink-3 mb-3">共 {total} 种成分</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((i) => (
              <Link
                key={i.id}
                to={`/ingredients/${i.id}`}
                className="block bg-card rounded-card shadow-card p-5 hover:ring-2 hover:ring-brand/40 transition-shadow"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-[15px] leading-snug">{i.cn_name || i.inci_name}</div>
                    {i.inci_name && <div className="text-xs text-ink-3 mt-1 break-all">{i.inci_name}</div>}
                    {i.cas_no && <div className="text-xs text-ink-3 mt-0.5">CAS {i.cas_no}</div>}
                  </div>
                  {i.assertion_count > 0
                    ? <span className="badge-ok flex-shrink-0">断言 {i.assertion_count}</span>
                    : <span className="badge-muted flex-shrink-0">暂无证据</span>}
                </div>
              </Link>
            ))}
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
