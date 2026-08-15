import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from './common'

// Tab 文案 → canon 参数（「抗老」是文案，canon 用「抗皱」；枚举见 Task 2b 接口）
const TABS = [
  ['美白', '美白'],
  ['抗老', '抗皱'],
  ['保湿', '保湿'],
  ['祛痘', '控油祛痘'],
]

export default function EfficacyBoard({ limit = 5 }) {
  const [tab, setTab] = useState(0)
  const canon = TABS[tab][1]
  const { data, loading, error } = useFetch(
    () => api.rankingsEfficacy(canon, limit),
    [canon, limit]
  )

  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-4">
        {TABS.map(([label], i) => (
          <button
            key={label}
            onClick={() => setTab(i)}
            className={
              i === tab
                ? 'fairy-chip !bg-rosewood !text-white !border-rosewood font-semibold'
                : 'fairy-chip hover:bg-rosewood/20 transition-colors'
            }
          >
            {label}
          </button>
        ))}
      </div>

      {loading && <Loading />}
      {error && <LoadError error={error} />}
      {data && data.items.length === 0 && (
        <div className="fairy-panel-dim py-10 text-center text-pearl-ink-3 text-sm">
          该功效暂无足够数据
        </div>
      )}
      {data && data.items.length > 0 && (
        <ol className="space-y-2">
          {data.items.map((p, i) => (
            <li key={p.id}>
              <Link
                to={`/products/${p.id}`}
                className="fairy-panel flex items-center gap-3 px-4 py-3 hover:bg-white/70 transition-colors"
              >
                <span className="font-num text-lg font-bold w-7 text-center flex-shrink-0 text-rosewood">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold truncate">
                    {p.name}
                    {p.brand && (
                      <span className="ml-2 text-xs font-normal text-pearl-ink-3">{p.brand}</span>
                    )}
                  </span>
                  <span className="block text-xs text-pearl-ink-2 mt-0.5">
                    {p.ingredient_hits} 个成分有证据 · {p.human_evidence} 条真人实验
                  </span>
                </span>
                <span className="text-pearl-ink-3 flex-shrink-0">→</span>
              </Link>
            </li>
          ))}
        </ol>
      )}

      <p className="mt-4 text-xs text-pearl-ink-3">按成分证据强度排序，非效果排名</p>
    </div>
  )
}
