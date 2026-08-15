import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from '../components/common'
import EfficacyBoard from '../components/EfficacyBoard'

// 浓度推断覆盖的产品子集（2026-08-15 实测 17 款，即 product_ingredients.conc_low
// 非空的产品，对应 data/research 推断结果）。后端无「是否有推断」列表接口，
// 全库 N+1 探测不可行，故只在该子集内并行请求（≤20 个上限内）
const CONC_PRODUCT_IDS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 72, 73, 75, 76, 77, 78, 2810, 3202]

// 并行拉取推断子集的 产品信息 + 浓度推断；单产品失败/无推断剔除，不拖垮整榜
async function fetchConcProducts() {
  const rows = await Promise.all(
    CONC_PRODUCT_IDS.map(async (id) => {
      try {
        const [info, conc] = await Promise.all([api.product(id), api.productConcentration(id)])
        return conc.inferred ? { id: info.id, name: info.name, brand: info.brand, conc } : null
      } catch {
        return null
      }
    })
  )
  return rows.filter(Boolean)
}

// 产品核验榜行数据：达标率 = 估计区间整体过文献起效线的判定数 / 可判定总数
// （verdict=unknown 缺文献起效线不算判定，不计入分母）
function buildVerifyRows(rows) {
  return rows
    .map((p) => {
      const verdicts = p.conc.estimates.flatMap((e) => e.dose.map((d) => d.verdict))
      const judged = verdicts.filter((v) => v !== 'unknown')
      const eff = judged.filter((v) => v === 'effective').length
      return { ...p, judged: judged.length, eff, rate: judged.length ? eff / judged.length : 0 }
    })
    .filter((p) => p.judged > 0)
    .sort((a, b) => b.rate - a.rate || b.judged - a.judged || a.id - b.id)
}

// 性价比榜行数据：每起效成本 = 各成分「达最低文献起效线的每日折算成本」的最小值（升序）
function buildCostRows(rows) {
  return rows
    .map((p) => {
      const costs = p.conc.estimates
        .map((e) => e.cost_per_effective_dose)
        .filter((c) => c != null)
      return costs.length ? { ...p, minCost: Math.min(...costs) } : null
    })
    .filter(Boolean)
    .sort((a, b) => a.minCost - b.minCost || a.id - b.id)
}

function ProductRow({ rank, id, name, brand, right, sub }) {
  return (
    <li>
      <Link
        to={`/products/${id}`}
        className="fairy-panel flex items-center gap-3 px-4 py-3 hover:bg-white/70 transition-colors"
      >
        <span className="font-num text-lg font-bold w-7 text-center flex-shrink-0 text-rosewood">
          {rank}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold truncate">
            {name}
            {brand && (
              <span className="ml-2 text-xs font-normal text-pearl-ink-3">{brand}</span>
            )}
          </span>
          <span className="block text-xs text-pearl-ink-2 mt-0.5">{sub}</span>
        </span>
        <span className="flex-shrink-0 text-right">{right}</span>
      </Link>
    </li>
  )
}

// 成分证据榜：按挂证据的断言总数降序 Top20
function IngredientEvidenceBoard() {
  // 不带 limit 返回全量纯 list（651 个有断言成分，payload 小），
  // 避免 limit=200 按 id 截断漏掉高断言数成分导致排错
  const { data, loading, error } = useFetch(
    () => api.ingredients({ has_evidence: 'true' }),
    []
  )
  if (loading) return <Loading />
  if (error) return <LoadError error={error} />
  const top = [...data].sort((a, b) => b.assertion_count - a.assertion_count || a.id - b.id).slice(0, 20)
  return (
    <div>
      <ol className="space-y-2">
        {top.map((ing, i) => (
          <li key={ing.id}>
            <Link
              to={`/ingredients/${ing.id}`}
              className="fairy-panel flex items-center gap-3 px-4 py-3 hover:bg-white/70 transition-colors"
            >
              <span className="font-num text-lg font-bold w-7 text-center flex-shrink-0 text-rosewood">
                {i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold truncate">
                  {ing.cn_name || ing.inci_name}
                </span>
                <span className="block text-xs text-pearl-ink-2 mt-0.5 truncate">{ing.inci_name}</span>
              </span>
              <span className="flex-shrink-0 text-right">
                <span className="font-num text-base font-bold text-pearl-ink">{ing.assertion_count}</span>
                <span className="text-xs text-pearl-ink-3 ml-1">条断言</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-xs text-pearl-ink-3">
        按挂真实证据的功效断言总数排序；含原料商宣称等降级证据口径，明细见成分详情页
      </p>
    </div>
  )
}

// 核验榜 + 性价比榜：共享一次推断子集拉取
function ConcentrationBoards() {
  const { data: rows, loading, error } = useFetch(fetchConcProducts, [])
  if (loading) return <Loading text="正在核验推断产品子集…" />
  if (error) return <LoadError error={error} />
  // 干净数据源缺失（子集全部拉取失败/无推断）时降级占位，不硬排
  if (!rows || rows.length === 0) {
    return (
      <div className="fairy-panel-dim py-10 text-center text-pearl-ink-3 text-sm">
        浓度推断数据覆盖中，暂无足够可核验产品，稍后再来
      </div>
    )
  }
  const verify = buildVerifyRows(rows)
  const costs = buildCostRows(rows)
  const noJudge = rows.length - verify.length
  return (
    <div className="grid md:grid-cols-2 gap-5">
      {/* 产品核验榜：剂量达标率 */}
      <div>
        <h3 className="font-display text-base tracking-wider mb-3">产品核验榜</h3>
        {verify.length === 0 ? (
          <div className="fairy-panel-dim py-10 text-center text-pearl-ink-3 text-sm">
            推断产品均缺文献起效线，无法判定，暂不排名
          </div>
        ) : (
          <ol className="space-y-2">
            {verify.map((p, i) => (
              <ProductRow
                key={p.id}
                rank={i + 1}
                id={p.id}
                name={p.name}
                brand={p.brand}
                sub={`${p.eff}/${p.judged} 项判定达标（估计区间过文献起效线）`}
                right={
                  <span className="font-num text-base font-bold text-pearl-ink">
                    {Math.round(p.rate * 100)}%
                  </span>
                }
              />
            ))}
          </ol>
        )}
        <p className="mt-4 text-xs text-pearl-ink-3">
          限有官方降序成分表的 {rows.length} 款；浓度为估计值
          {noJudge > 0 && `；另 ${noJudge} 款无文献起效线可判定，未列入`}
        </p>
      </div>

      {/* 性价比榜：每起效成本升序 */}
      <div>
        <h3 className="font-display text-base tracking-wider mb-3">性价比榜</h3>
        {costs.length === 0 ? (
          <div className="fairy-panel-dim py-10 text-center text-pearl-ink-3 text-sm">
            推断产品均缺官方价或起效线，无法折算成本，暂不排名
          </div>
        ) : (
          <ol className="space-y-2">
            {costs.map((p, i) => (
              <ProductRow
                key={p.id}
                rank={i + 1}
                id={p.id}
                name={p.name}
                brand={p.brand}
                sub={`官方价 ¥${p.conc.price ?? '—'} / ${p.conc.spec ?? '—'}`}
                right={
                  <span>
                    <span className="font-num text-base font-bold text-pearl-ink">
                      ¥{p.minCost.toFixed(2)}
                    </span>
                    <span className="text-xs text-pearl-ink-3 ml-1">/天（估计）</span>
                  </span>
                }
              />
            ))}
          </ol>
        )}
        <p className="mt-4 text-xs text-pearl-ink-3">
          每起效成本 = 达最低文献起效浓度的每日折算成本（按 1ml 用量，估计值）；
          限有官方降序成分表且有官方价的 {costs.length} 款
        </p>
      </div>
    </div>
  )
}

export default function Rankings() {
  return (
    <div className="pearl-page">
      <h1 className="font-display text-2xl tracking-[0.2em] grad-text mb-1">排行榜</h1>
      <p className="text-xs text-pearl-ink-2 mb-4">功效证据 · 成分证据 · 剂量核验 · 性价比</p>

      {/* 口径横幅：固定页顶 */}
      <div className="pearl-notice">
        本榜按证据强度 / 性价比排序，不是效果排名；浓度为估计值；无数据项不排不猜
      </div>

      {/* 功效产品榜（主榜，Tab 切换功效族） */}
      <div className="glass-card scroll-mt-24" id="board">
        <h2 className="pearl-title">功效产品榜</h2>
        <EfficacyBoard limit={20} />
      </div>

      {/* 成分证据榜 */}
      <div className="glass-card">
        <h2 className="pearl-title">成分证据榜</h2>
        <IngredientEvidenceBoard />
      </div>

      {/* 核验榜 + 性价比榜（推断产品子集） */}
      <div className="glass-card">
        <h2 className="pearl-title">剂量核验与性价比</h2>
        <ConcentrationBoards />
      </div>
    </div>
  )
}
