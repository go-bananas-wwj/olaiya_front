import { api } from '../api'
import { useFetch, Loading } from './common'

// 剂量判定徽章：verdict → 文案与配色（红系 Tailwind 默认色板，与 ok/warn 徽章同构）
const VERDICT = {
  effective: { text: '达标', cls: 'badge-ok' },
  uncertain: { text: '存疑', cls: 'badge-warn' },
  insufficient: { text: '不足', cls: 'badge bg-red-100 text-red-700' },
  unknown: { text: '无法判定', cls: 'badge-muted' },
}

// 对数刻度 0.01% – 100%：化妆品浓度跨 4 个数量级，线性刻度下低浓度区间不可见
const AXIS_MIN = 0.01
const AXIS_MAX = 100
const pos = (v) => {
  const c = Math.min(Math.max(v, AXIS_MIN), AXIS_MAX)
  return ((Math.log10(c) - Math.log10(AXIS_MIN)) / (Math.log10(AXIS_MAX) - Math.log10(AXIS_MIN))) * 100
}

const fmt = (v) => (v == null || Number.isNaN(v) ? '—' : v >= 1 ? v.toFixed(1) : v.toFixed(2))

function doseTitle(est, d) {
  const effLow = d.eff_low != null ? `${fmt(d.eff_low)}%` : '—'
  return `推断区间 ${fmt(est.low)}% – ${fmt(est.high)}% vs 文献起效浓度 ${effLow}`
}

function DoseBadge({ est, d }) {
  const v = VERDICT[d.verdict] || VERDICT.unknown
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-ink-2">{d.efficacy}</span>
      <span className={v.cls} title={doseTitle(est, d)}>{v.text}</span>
    </span>
  )
}

function EstimateRow({ est }) {
  const l = pos(est.low)
  const r = pos(est.high)
  return (
    <div className="py-3 border-b border-line last:border-b-0">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="text-sm font-medium">
          {est.cn_name || est.inci_name}
          {est.inci_name && est.cn_name && est.inci_name !== est.cn_name && (
            <span className="text-xs text-ink-3 ml-2">{est.inci_name}</span>
          )}
        </div>
        <div className="text-xs text-ink-2 tabular-nums">{fmt(est.low)}% – {fmt(est.high)}%</div>
      </div>
      <div className="relative h-2.5 mt-2 rounded-full bg-bg">
        <div
          className="absolute h-full rounded-full bg-brand/60"
          style={{ left: `${l}%`, width: `${Math.max(r - l, 0.8)}%` }}
        />
        {est.disclosed_conc != null && (
          <div
            className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-ok rounded-full"
            style={{ left: `calc(${pos(est.disclosed_conc)}% - 1px)` }}
            title={`官方披露浓度锚点 ${fmt(est.disclosed_conc)}%`}
          />
        )}
      </div>
      {est.dose && est.dose.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
          {est.dose.map((d, i) => <DoseBadge key={i} est={est} d={d} />)}
        </div>
      )}
    </div>
  )
}

// 浓度推断区块（产品详情页）：区间横条 + 披露锚点竖线 + 剂量判定徽章
export default function ConcentrationPanel({ productId }) {
  const { data, loading, error } = useFetch(() => api.productConcentration(productId), [productId])

  return (
    <div className="card">
      <h2 className="card-title">浓度推断（估计值）</h2>
      <div className="notice">以下浓度为模型估计值，非官方数据</div>
      {loading ? (
        <Loading />
      ) : error ? (
        <div className="notice !mb-0">浓度推断数据加载失败（{error}）</div>
      ) : !data.inferred ? (
        <div className="bg-bg text-ink-3 rounded-[10px] px-4 py-2.5 text-xs leading-relaxed">
          该产品暂无官方降序成分表，未做浓度推断
        </div>
      ) : (
        <>
          <div className="text-xs text-ink-3 mb-2 flex flex-wrap gap-x-4 gap-y-1">
            <span>横轴为对数刻度（{AXIS_MIN}% – {AXIS_MAX}%）</span>
            <span>
              <span className="inline-block w-0.5 h-3 bg-ok rounded-full align-middle mr-1" />
              竖线 = 官方披露浓度锚点
            </span>
          </div>
          <div>
            {(data.estimates || []).map((est) => <EstimateRow key={est.ingredient_id} est={est} />)}
          </div>
        </>
      )}
    </div>
  )
}
