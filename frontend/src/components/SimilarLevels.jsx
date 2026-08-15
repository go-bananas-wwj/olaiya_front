import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading } from './common'

// 三级相似口径与置信度标签（与后端 similar_levels 一一对应；总纲 I3「诚实版」相似性报告）
const LEVELS = [
  {
    key: 'l1', title: 'L1 成分集合', badge: '确定性', badgeCls: 'pearl-badge-ok',
    desc: 'Jaccard(成分集合) = 共有成分 / 并集成分，确定性计算，可复算',
  },
  {
    key: 'l2', title: 'L2 剂量级', badge: '估计', badgeCls: 'pearl-badge-warn',
    desc: '推断浓度区间中点向量的 min 加权余弦；仅对有推断浓度的产品可比，剂量为模型估计值',
  },
  {
    key: 'l3', title: 'L3 功效级', badge: '证据统计', badgeCls: 'pearl-badge-iris',
    desc: '功效指纹余弦（排除「其他」维），相对排序信号，非功效承诺',
  },
]

const pct = (s) => `${(s * 100).toFixed(1)}%`

function SimCard({ item, meta, productId }) {
  return (
    <div className="fairy-panel hover:bg-white/75 px-3.5 py-2.5 transition-colors">
      <Link to={`/products/${item.id}`} className="block">
        <div className="flex items-baseline justify-between gap-2">
          <div className="text-sm font-medium leading-snug text-pearl-ink">{item.name}</div>
          <div className="text-xs text-rosewood font-semibold font-num tabular-nums shrink-0">{pct(item.score)}</div>
        </div>
        <div className="text-xs text-pearl-ink-3 mt-0.5">{item.brand}</div>
        {meta && <div className="text-xs text-pearl-ink-3 mt-1">{meta}</div>}
      </Link>
      <div className="mt-1.5">
        <Link
          to={`/compare?a=${productId}&b=${item.id}`}
          className="pearl-badge-iris hover:ring-1 hover:ring-iris"
        >
          加入对比 ⇄
        </Link>
      </div>
    </div>
  )
}

function LevelColumn({ level, data, note, productId }) {
  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-pearl-ink">{level.title}</h3>
        <span className={level.badgeCls}>{level.badge}</span>
      </div>
      <p className="text-xs text-pearl-ink-3 leading-relaxed mt-1.5">{level.desc}</p>
      <div className="mt-3 space-y-2">
        {level.key === 'l2' && !data.l2.available ? (
          <div className="fairy-panel-dim text-pearl-ink-3 px-3.5 py-2.5 text-xs leading-relaxed">
            {data.l2.reason}
          </div>
        ) : (
          (() => {
            const items = level.key === 'l2' ? data.l2.similar : data[level.key]
            if (!items || items.length === 0) {
              return <div className="text-xs text-pearl-ink-3 py-2">暂无可比对的产品</div>
            }
            return items.map((item) => (
              <SimCard
                key={item.id}
                item={item}
                productId={productId}
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
        <p className="text-xs text-pearl-ink-3 leading-relaxed mt-2">{note}</p>
      )}
    </div>
  )
}

// 语义相似栏（第四栏）：BGE-M3 成分表文本向量余弦，独立请求 /similar，索引未构建时降级
function SemanticColumn({ productId }) {
  const { data, loading, error } = useFetch(() => api.productSimilar(productId), [productId])
  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-pearl-ink">语义相似</h3>
        <span className="pearl-badge-info">语义</span>
      </div>
      <p className="text-xs text-pearl-ink-3 leading-relaxed mt-1.5">
        成分表文本向量（BGE-M3）余弦相似；可发现成分集合并不重叠但配方文本接近的产品
      </p>
      <div className="mt-3 space-y-2">
        {loading ? (
          <Loading />
        ) : error ? (
          <div className="fairy-panel-dim text-pearl-ink-3 px-3.5 py-2.5 text-xs leading-relaxed">
            语义相似加载失败（{error}）
          </div>
        ) : !data.similar ? (
          <div className="fairy-panel-dim text-pearl-ink-3 px-3.5 py-2.5 text-xs leading-relaxed">
            {data.reason || '相似索引未构建'}
          </div>
        ) : data.similar.length === 0 ? (
          <div className="text-xs text-pearl-ink-3 py-2">暂无可比对的产品</div>
        ) : (
          data.similar.map((item) => (
            <SimCard key={item.id} item={item} productId={productId} meta={null} />
          ))
        )}
      </div>
    </div>
  )
}

// 「相似产品」区块（产品详情页，珍珠贝母版）：L1 成分集合 / L2 剂量级 / L3 功效级 / 语义相似 四栏
export default function SimilarLevels({ productId }) {
  const { data, loading, error } = useFetch(() => api.productSimilarLevels(productId), [productId])

  return (
    <div className="glass-card">
      <h2 className="pearl-title">相似产品（真平替候选）</h2>
      <div className="pearl-notice">
        四种口径独立、互不替代：成分集合是确定性比对，剂量级基于推断浓度（估计值），
        功效级是证据库统计信号，语义相似是文本向量接近度。相似 ≠ 功效相同，任何一栏都不是「功效等同」承诺。
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <div className="pearl-notice !mb-0">相似产品数据加载失败（{error}）</div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          {LEVELS.map((level) => (
            <LevelColumn key={level.key} level={level} data={data} note={data.note} productId={productId} />
          ))}
          <SemanticColumn productId={productId} />
        </div>
      )}
    </div>
  )
}
