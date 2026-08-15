import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
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
  const location = useLocation()
  const rootRef = useRef(null)
  // 锚点深链：#board-美白 等直达对应 Tab（排行榜页入站/外部分享）。
  // location.hash 是 percent-encoded，比较前须解码
  const hash = decodeURIComponent(location.hash || '')
  const hashTab = TABS.findIndex(([label]) => hash === `#board-${label}`)
  const [tab, setTab] = useState(hashTab >= 0 ? hashTab : 0)
  const canon = TABS[tab][1]
  const { data, loading, error } = useFetch(
    () => api.rankingsEfficacy(canon, limit),
    [canon, limit]
  )

  // 同页哈希跳转（如 /rankings → /rankings#board-保湿 不触发 remount）：锚点变化时切 Tab
  useEffect(() => {
    if (hashTab >= 0 && hashTab !== tab) setTab(hashTab)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hashTab])

  // 入站锚点跳转：内容异步渲染，原生锚点定位不到，数据落地后手动滚动
  useEffect(() => {
    if (!data) return
    if (hash === '#board' || hashTab >= 0) {
      rootRef.current?.scrollIntoView({ block: 'start' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, hash])

  return (
    <div ref={rootRef} id={`board-${TABS[tab][0]}`} className="scroll-mt-24">
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
