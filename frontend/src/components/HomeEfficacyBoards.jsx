import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from './common'

const RANKINGS = [
  ['美白产品榜', '美白'],
  ['抗老产品榜', '抗皱'],
  ['保湿产品榜', '保湿'],
  ['祛痘产品榜', '控油祛痘'],
]

function RankingCard({ label, canon }) {
  const { data, loading, error } = useFetch(
    () => api.rankingsEfficacy(canon, 3),
    [canon]
  )

  return (
    <section className="home-ranking-card">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h3 className="home-ranking-title">{label}</h3>
        <Link to={`/rankings#board-${label.replace('产品榜', '')}`} className="home-ranking-more">
          查看全部
        </Link>
      </div>
      {loading && <p className="home-ranking-state">正在加载…</p>}
      {error && <p className="home-ranking-state">暂时无法加载</p>}
      {data && data.items.length === 0 && <p className="home-ranking-state">暂无足够数据</p>}
      {data && data.items.length > 0 && (
        <ol className="space-y-1.5">
          {data.items.map((product, index) => (
            <li key={product.id}>
              <Link to={`/products/${product.id}`} className="home-ranking-row">
                <span className="home-ranking-no">{index + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-pearl-ink">{product.name}</span>
                  <span className="block truncate text-xs text-pearl-ink-2">
                    {product.brand} · {product.ingredient_hits} 个证据成分
                  </span>
                </span>
                <span aria-hidden="true" className="text-pearl-ink-3">›</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export default function HomeEfficacyBoards() {
  return (
    <section className="home-rankings" aria-label="功效产品榜">
      {RANKINGS.map(([label, canon]) => <RankingCard key={canon} label={label} canon={canon} />)}
    </section>
  )
}
