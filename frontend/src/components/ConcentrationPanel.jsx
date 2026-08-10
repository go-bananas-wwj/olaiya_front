import DoseChart, { fmt } from './DoseChart'
import { Loading } from './common'

// 浓度推断区块（产品详情页，珍珠贝母版）：全部推断成分的剂量对照条。
// 数据由页面统一预取后传入（判决条与宣称卡共用同一份），本组件不再自行请求。
// 浓度为模型估计值（p5/p95 区间），非实测；展示必须带「估计」语义（数据铁律）。
export default function ConcentrationPanel({ conc }) {
  const { data, loading, error } = conc

  return (
    <div className="glass-card">
      <h2 className="pearl-title">浓度推断（估计值）</h2>
      <div className="pearl-notice">以下浓度为模型估计值，非官方数据</div>
      {loading ? (
        <Loading />
      ) : error ? (
        <div className="pearl-notice !mb-0">浓度推断数据加载失败（{error}）</div>
      ) : !data.inferred ? (
        <div className="bg-white/40 text-pearl-ink-3 rounded-2xl px-4 py-2.5 text-xs leading-relaxed border border-white/60">
          该产品暂无官方降序成分表，未做浓度推断——查不到本身也是信号，不伪造位次。
        </div>
      ) : (
        <>
          <div className="text-xs text-pearl-ink-3 mb-3 flex flex-wrap gap-x-4 gap-y-1">
            <span>横轴为对数刻度（0.01% – 100%）</span>
            <span>
              <span className="inline-block w-2.5 h-2 rounded-sm bg-[#b9aa99] align-middle mr-1" />
              推断区间（估计）
            </span>
            <span>
              <span className="inline-block w-0.5 h-2.5 bg-rosewood rounded-full align-middle mr-1" />
              文献起效线
            </span>
            <span>
              <span className="inline-block w-0.5 h-2.5 bg-mint rounded-full align-middle mr-1" />
              官方披露锚点
            </span>
          </div>
          <div className="space-y-2.5">
            {(data.estimates || []).map((est) => <EstimateCard key={est.ingredient_id} est={est} />)}
          </div>
        </>
      )}
    </div>
  )
}

function EstimateCard({ est }) {
  const hasDose = est.dose && est.dose.length > 0
  return (
    <div className="bg-white/50 rounded-2xl px-4 py-3 border border-white/70">
      {hasDose ? (
        <div className="space-y-2.5">
          {est.dose.map((d, i) => <DoseChart key={i} est={est} d={d} compact />)}
        </div>
      ) : (
        // 有推断区间但无功效断言：只画区间带，如实标注无剂量判定
        <div>
          <div className="flex items-baseline justify-between gap-3 flex-wrap">
            <div className="text-sm font-semibold text-pearl-ink">
              {est.cn_name || est.inci_name}
              {est.inci_name && est.cn_name && est.inci_name !== est.cn_name && (
                <span className="text-xs text-pearl-ink-3 font-normal ml-2">{est.inci_name}</span>
              )}
            </div>
            <span className="pearl-badge-muted">无剂量判定</span>
          </div>
          <div className="text-xs text-pearl-ink-2 mt-1.5 font-num tabular-nums">
            估计含量约 {fmt(est.low)}–{fmt(est.high)}%（估计值）· 证据库无该成分起效浓度文献
          </div>
        </div>
      )}
      {est.disclosed_conc != null && (
        <div className="mt-2 text-xs text-[#2f7a68]">
          官方披露浓度锚点 <span className="font-num font-semibold tabular-nums">{fmt(est.disclosed_conc)}%</span>
        </div>
      )}
      {est.cost_per_effective_dose != null && (
        <div className="mt-1.5 text-xs text-pearl-ink-2" title={est.cost_note || undefined}>
          每起效成本
          <span className="text-rosewood font-semibold font-num tabular-nums mx-1">
            ¥{est.cost_per_effective_dose.toFixed(2)}/天
          </span>
          <span className="text-pearl-ink-3">（估计）</span>
        </div>
      )}
    </div>
  )
}
