// 剂量对照条（hero 组件，bullet chart 形态）：
// 灰色横带 = 推断浓度区间（模型估计值，p5–p95），醒目竖线 = 文献起效浓度线，
// 一眼看出「够不够量」。对数刻度 0.01%–100%（浓度跨数量级，线性刻度下低浓度不可见）。
// 数据契约：后端 /api/products/{id}/concentration 的 estimates[] 与 dose[]（见 dosecheck.py 注释，
// low/high 为估计值，verdict 仅表达估计区间与文献起效线的相对关系，不构成功效承诺）。

const AXIS_MIN = 0.01
const AXIS_MAX = 100
const pos = (v) => {
  const c = Math.min(Math.max(v, AXIS_MIN), AXIS_MAX)
  return ((Math.log10(c) - Math.log10(AXIS_MIN)) / (Math.log10(AXIS_MAX) - Math.log10(AXIS_MIN))) * 100
}

const fmt = (v) => (v == null || Number.isNaN(v) ? '—' : v >= 1 ? v.toFixed(1) : v.toFixed(2))

// verdict → 说人话的结论（与后端 dosec.verdict_for 枚举一一对应）
const VERDICT = {
  effective: { text: '大概率够量', cls: 'pearl-badge-ok' },
  uncertain: { text: '可能踩线，说不准', cls: 'pearl-badge-warn' },
  insufficient: { text: '大概率不够量', cls: 'pearl-badge-bad' },
  unknown: { text: '文献没给浓度线，没法比', cls: 'pearl-badge-muted' },
  trace_level: { text: '微量也可能起效（看原料披露）', cls: 'pearl-badge-warn' },
}

// est: estimates[] 中一项；d: 该项 dose[] 中一条判定
export default function DoseChart({ est, d, compact = false }) {
  const v = VERDICT[d.verdict] || VERDICT.unknown
  const l = pos(est.low)
  const r = pos(est.high)
  const hasLine = d.eff_low != null

  const plain = hasLine
    ? `估计含量约 ${fmt(est.low)}–${fmt(est.high)}%（估计值）· 文献说 ${fmt(d.eff_low)}% 起就有用 → ${v.text}`
    : `估计含量约 ${fmt(est.low)}–${fmt(est.high)}%（估计值）· 文献没给起效浓度 → ${v.text}`

  return (
    <div className={compact ? '' : 'fairy-panel px-4 py-3'}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="text-sm font-semibold text-pearl-ink">
          {est.cn_name || est.inci_name}
          <span className="text-xs text-pearl-ink-3 font-normal ml-2">{d.efficacy}</span>
        </div>
        <span className={v.cls}>{v.text}</span>
      </div>

      {/* bullet chart：灰带 = 推断区间（估计），竖线 = 文献起效线 */}
      <div className="relative h-3.5 mt-2.5 rounded-full bg-[#ddd0c0]">
        <div
          className="absolute top-0.5 bottom-0.5 rounded-full bg-[#a3937f]"
          style={{ left: `${l}%`, width: `${Math.max(r - l, 1)}%` }}
          title={`推断浓度区间 ${fmt(est.low)}% – ${fmt(est.high)}%（估计值）`}
        />
        {hasLine && (
          <div
            className="absolute -top-1 -bottom-1 w-1 rounded-full bg-rosewood shadow-[0_0_0_2px_rgba(255,255,255,.8)]"
            style={{ left: `calc(${pos(d.eff_low)}% - 2px)` }}
            title={`文献起效浓度线 ${fmt(d.eff_low)}%`}
          />
        )}
        {est.disclosed_conc != null && (
          <div
            className="absolute -top-0.5 -bottom-0.5 w-0.5 rounded-full bg-mint"
            style={{ left: `calc(${pos(est.disclosed_conc)}% - 1px)` }}
            title={`官方披露浓度锚点 ${fmt(est.disclosed_conc)}%`}
          />
        )}
      </div>

      <div className="mt-2 text-xs text-pearl-ink-2 leading-relaxed">{plain}</div>
      {!compact && (
        <div className="mt-1.5 text-[11px] text-pearl-ink-3 flex flex-wrap gap-x-4 gap-y-0.5">
          <span>横轴对数刻度 {AXIS_MIN}%–{AXIS_MAX}%</span>
          <span>
            <span className="inline-block w-2.5 h-2 rounded-sm bg-[#a3937f] align-middle mr-1" />
            推断区间（估计）
          </span>
          {hasLine && (
            <span>
              <span className="inline-block w-0.5 h-2.5 bg-rosewood rounded-full align-middle mr-1" />
              文献起效线
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export { AXIS_MIN, AXIS_MAX, pos, fmt, VERDICT }
