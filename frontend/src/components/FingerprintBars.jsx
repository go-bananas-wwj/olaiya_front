import { Loading } from './common'

// —— 功效指纹条（横向条形图）：维=规范功效族，值=族强度 Σ(剂量因子×证据强度) ——
// 数据：GET /api/products/{id}/fingerprint；分值为相对排序信号，非功效承诺。
export default function FingerprintBars({ fp }) {
  return (
    <div className="glass-card">
      <h2 className="pearl-title">功效指纹</h2>
      {fp.loading ? (
        <Loading />
      ) : fp.error ? (
        <div className="pearl-notice !mb-0">功效指纹加载失败（{fp.error}）</div>
      ) : !fp.data || Object.keys(fp.data.fingerprint || {}).length === 0 ? (
        <div className="fairy-panel-dim text-pearl-ink-3 px-3.5 py-2.5 text-xs leading-relaxed">
          证据不足，未生成指纹（成分证据库中无有效功效断言支撑）。
        </div>
      ) : (
        <FingerprintBody data={fp.data} />
      )}
    </div>
  )
}

function FingerprintBody({ data }) {
  const entries = Object.entries(data.fingerprint) // 后端已按得分降序
  const max = entries[0][1]
  const cov = data.coverage || {}
  return (
    <>
      <div className="space-y-2.5">
        {entries.map(([family, score]) => (
          <div key={family} className="flex items-center gap-3">
            <div className="w-16 shrink-0 text-[13px] text-pearl-ink">{family}</div>
            <div className="flex-1 h-3.5 rounded-full bg-white/60 border border-[rgba(138,90,106,0.15)] overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max((score / max) * 100, 4)}%`,
                  background: 'linear-gradient(90deg, #b06a8a, #8a7ab8)',
                }}
              />
            </div>
            <div className="w-12 shrink-0 text-right text-xs text-pearl-ink-2 font-num tabular-nums">
              {score.toFixed(2)}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 text-xs text-pearl-ink-3 leading-relaxed">
        覆盖：<b className="font-num">{cov.ingredients_with_assertion}</b>/{cov.ingredients_total} 个成分有功效断言；
        法规类 / 防腐族 / 原料商宣称断言不计分（已排除 <b className="font-num">{cov.excluded_count}</b> 条）。
        分值为相对排序信号，非功效承诺；剂量因子基于推断浓度（估计值），无推断时按保守默认计。
      </div>
    </>
  )
}
