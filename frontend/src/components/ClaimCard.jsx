// 功效宣称依据卡片（产品详情页）：数据即企业向 NMPA 公示的《功效宣称依据摘要》
export default function ClaimCard({ claim: c, nmpaId }) {
  const fields = [
    ['评价方法', c.method_name],
    ['方法来源', c.method_source],
    ['功效判定指标', c.metric],
    ['试验起止日期', c.test_period && !c.test_period.startsWith('1970') ? c.test_period : null],
    ['评价机构', c.institution],
  ].filter(([, v]) => v)

  return (
    <div className="border border-line rounded-xl p-4 md:p-5 mb-4 hover:shadow-card transition-shadow">
      <div className="flex items-center gap-2.5 flex-wrap">
        <span className="text-[15px] font-bold bg-brand-soft text-brand px-3.5 py-1 rounded-full">
          【{c.claim}】
        </span>
        {c.eval_category && <span className="badge-warn">{c.eval_category}</span>}
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {fields.map(([k, v]) => (
          <div key={k}>
            <div className="kv-label">{k}</div>
            <div className="kv-value">{v}</div>
          </div>
        ))}
        {c.result_summary && (
          <div className="md:col-span-2 lg:col-span-3 bg-bg rounded-[10px] px-3.5 py-2.5">
            <div className="kv-label">试验结果简述</div>
            <div className="text-[13px] text-ink-2">{c.result_summary}</div>
          </div>
        )}
      </div>
      <div className="mt-3 pt-2.5 border-t border-dashed border-line text-xs text-ink-3 flex flex-wrap gap-x-1.5 items-center">
        出处：<b className="text-ok font-semibold">NMPA《功效宣称依据摘要》</b>
        {nmpaId && <span>（备案号 {nmpaId}）</span>}
      </div>
    </div>
  )
}
