import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading } from './common'

// 三级相似口径与置信度标签（与后端 similar_levels 一一对应；总纲 I3「诚实版」相似性报告）
const LEVELS = [
  {
    key: 'l1', title: 'L1 成分集合', badge: '确定性', badgeCls: 'badge-ok',
    desc: 'Jaccard(成分集合) = 共有成分 / 并集成分，确定性计算，可复算',
  },
  {
    key: 'l2', title: 'L2 剂量级', badge: '估计', badgeCls: 'badge-warn',
    desc: '推断浓度区间中点向量的 min 加权余弦；仅对有推断浓度的产品可比，剂量为模型估计值',
  },
  {
    key: 'l3', title: 'L3 功效级', badge: '证据统计', badgeCls: 'badge-brand',
    desc: '功效指纹余弦（排除「其他」维），相对排序信号，非功效承诺',
  },
]

const pct = (s) => `${(s * 100).toFixed(1)}%`

function SimCard({ item, meta }) {
  return (
    <Link
      to={`/products/${item.id}`}
      className="block bg-bg hover:bg-brand-soft/60 rounded-[10px] px-3.5 py-2.5 transition-colors"
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-sm font-medium leading-snug">{item.name}</div>
        <div className="text-xs text-brand font-semibold tabular-nums shrink-0">{pct(item.score)}</div>
      </div>
      <div className="text-xs text-ink-3 mt-0.5">{item.brand}</div>
      {meta && <div className="text-xs text-ink-3 mt-1">{meta}</div>}
    </Link>
  )
}

function LevelColumn({ level, data, note }) {
  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="text-sm font-semibold">{level.title}</h3>
        <span className={level.badgeCls}>{level.badge}</span>
      </div>
      <p className="text-xs text-ink-3 leading-relaxed mt-1.5">{level.desc}</p>
      <div className="mt-3 space-y-2">
        {level.key === 'l2' && !data.l2.available ? (
          <div className="bg-bg text-ink-3 rounded-[10px] px-3.5 py-2.5 text-xs leading-relaxed">
            {data.l2.reason}
          </div>
        ) : (
          (() => {
            const items = level.key === 'l2' ? data.l2.similar : data[level.key]
            if (!items || items.length === 0) {
              return <div className="text-xs text-ink-3 py-2">暂无可比对的产品</div>
            }
            return items.map((item) => (
              <SimCard
                key={item.id}
                item={item}
                meta={
                  level.key === 'l1'
                    ? `共有成分 ${item.shared} / 并集 ${item.union}`
                    : level.key === 'l3'
                      ? `${item.dimensions} 个共有功效维${item.top_shared_dims?.length ? `：${item.top_shared_dims.join('、')}` : ''}`
                      : null
                }
              />
            ))
          })()
        )}
      </div>
      {level.key === 'l3' && note && (
        <p className="text-xs text-ink-3 leading-relaxed mt-2">{note}</p>
      )}
    </div>
  )
}

// 「三级相似产品」区块（产品详情页）：L1 成分集合 / L2 剂量级 / L3 功效级 三栏
export default function SimilarLevels({ productId }) {
  const { data, loading, error } = useFetch(() => api.productSimilarLevels(productId), [productId])

  return (
    <div className="card">
      <h2 className="card-title">三级相似产品（真平替候选）</h2>
      <div className="notice">
        三个级别口径独立、互不替代：成分集合是确定性比对，剂量级基于推断浓度（估计值），
        功效级是证据库统计信号。任何一级都不是「功效等同」承诺。
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <div className="notice !mb-0">相似产品数据加载失败（{error}）</div>
      ) : (
        <div className="grid gap-6 md:grid-cols-3">
          {LEVELS.map((level) => (
            <LevelColumn key={level.key} level={level} data={data} note={data.note} />
          ))}
        </div>
      )}
    </div>
  )
}
