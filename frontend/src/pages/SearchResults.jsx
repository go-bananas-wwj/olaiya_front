import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from '../components/common'
import ProductCard from '../components/ProductCard'

export default function SearchResults() {
  const [params] = useSearchParams()
  const q = (params.get('q') || '').trim()
  const { data, loading, error } = useFetch(
    () => api.searchAll(q),
    [q],
  )

  return (
    <div>
      <div className="card">
        <h2 className="card-title">搜索「{q}」</h2>
        {!q && <p className="text-sm text-ink-3">在顶栏输入关键词，搜产品、成分或备案号。</p>}
      </div>

      {q && loading && <div className="card"><Loading /></div>}
      {q && error && <div className="card"><LoadError error={error} /></div>}

      {q && data && (
        <>
          <div className="card">
            <h3 className="card-title">产品（命中 {data.products.length} 款）</h3>
            {data.products.length === 0 ? (
              <p className="text-sm text-ink-3">
                没找到相关产品，<Link to="/decode" className="text-brand hover:underline">试试解码成分表 →</Link>
              </p>
            ) : (
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {data.products.map((p) => <ProductCard key={p.id} p={p} />)}
              </div>
            )}
          </div>

          <div className="card">
            <h3 className="card-title">成分（命中 {data.ingredients.length} 种）</h3>
            {data.ingredients.length === 0 ? (
              <p className="text-sm text-ink-3">没找到相关成分</p>
            ) : (
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {data.ingredients.map((i) => (
                  <Link
                    key={i.id}
                    to={`/ingredients/${i.id}`}
                    className="block bg-card rounded-card shadow-card p-5 hover:ring-2 hover:ring-brand/40 transition-shadow"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-semibold text-[15px] leading-snug">{i.cn_name || i.inci_name}</div>
                        {i.inci_name && <div className="text-xs text-ink-3 mt-1 break-all">{i.inci_name}</div>}
                      </div>
                      {i.assertion_count > 0
                        ? <span className="badge-ok flex-shrink-0">断言 {i.assertion_count}</span>
                        : <span className="badge-muted flex-shrink-0">暂无证据</span>}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
