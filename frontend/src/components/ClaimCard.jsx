import DoseChart from './DoseChart'

// 功效宣称依据卡片（产品详情页）：数据即企业向 NMPA 公示的《功效宣称依据摘要》。
// 头部三档徽章按 NMPA 公示的「评价类别」(eval_category) 说人话——这是 API 真实字段，
// 不做猜测；未公示类别（空值）落第三档。剂量对照条（DoseChart）为 hero 位，
// 由页面匹配该宣称对应的成分剂量判定后传入；无匹配时如实说明，不伪造。
const EVAL_TIER = {
  人体功效评价试验: { icon: '✅', text: '真人实测', cls: 'pearl-badge-ok' },
  消费者使用测试: { icon: '✅', text: '真人实测', cls: 'pearl-badge-ok' },
  实验室试验: { icon: '⚠️', text: '实验室试验', cls: 'pearl-badge-warn' },
  研究数据: { icon: '⚠️', text: '研究数据', cls: 'pearl-badge-warn' },
  文献资料: { icon: '⚠️', text: '仅文献资料', cls: 'pearl-badge-warn' },
}
const TIER_UNKNOWN = { icon: '❔', text: '未公示评价类别', cls: 'pearl-badge-muted' }

export default function ClaimCard({ claim: c, nmpaId, anchorId, doses }) {
  const tier = EVAL_TIER[c.eval_category] || TIER_UNKNOWN
  const fields = [
    ['评价方法', c.method_name],
    ['方法来源', c.method_source],
    ['功效判定指标', c.metric],
    ['试验起止日期', c.test_period && !c.test_period.startsWith('1970') ? c.test_period : null],
    ['评价机构', c.institution],
  ].filter(([, v]) => v)

  return (
    <div id={anchorId} className="scroll-mt-24 bg-white/50 border border-white/70 rounded-2xl p-4 md:p-5 mb-4">
      <div className="flex items-center gap-2.5 flex-wrap">
        <span className="font-display text-[17px] bg-rosewood-soft text-rosewood px-3.5 py-1 rounded-full">
          {c.claim}
        </span>
        <span className={tier.cls} title={c.eval_category ? `NMPA 公示评价类别：${c.eval_category}` : '备案摘要未公示评价类别'}>
          {tier.icon} {tier.text}
        </span>
        {c.eval_category && <span className="text-xs text-pearl-ink-3">{c.eval_category}</span>}
      </div>

      {/* hero 位：剂量对照条（够不够量，一眼可见） */}
      {doses && doses.length > 0 ? (
        <div className="mt-3 space-y-2.5">
          {doses.map(({ est, d }, i) => <DoseChart key={i} est={est} d={d} />)}
        </div>
      ) : (
        <div className="mt-3 bg-white/40 rounded-2xl px-4 py-2.5 text-xs text-pearl-ink-3 leading-relaxed border border-white/60">
          该宣称未匹配到带文献起效浓度的成分剂量判定——查不到本身也是信号，不做猜测。
        </div>
      )}

      <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {fields.map(([k, v]) => (
          <div key={k}>
            <div className="text-pearl-ink-3 text-xs mb-0.5">{k}</div>
            <div className="text-pearl-ink text-[13px] break-all">{v}</div>
          </div>
        ))}
        {c.result_summary && (
          <div className="md:col-span-2 lg:col-span-3 bg-white/40 rounded-2xl px-3.5 py-2.5 border border-white/60">
            <div className="text-pearl-ink-3 text-xs mb-0.5">试验结果简述</div>
            <div className="text-[13px] text-pearl-ink-2">{c.result_summary}</div>
          </div>
        )}
      </div>
      <div className="mt-3 pt-2.5 border-t border-dashed border-[#e2d8cc] text-xs text-pearl-ink-3 flex flex-wrap gap-x-1.5 items-center">
        出处：<b className="text-[#2f7a68] font-semibold">NMPA《功效宣称依据摘要》</b>
        {nmpaId && <span>（备案号 {nmpaId}）</span>}
      </div>
    </div>
  )
}
