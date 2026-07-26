const TYPE_LABEL = {
  paper: { text: '学术论文', cls: 'badge-brand' },
  patent: { text: '专利', cls: 'badge-warn' },
  regulation: { text: '法规标准', cls: 'badge-ok' },
  review: { text: '综述', cls: 'badge-brand' },
}

// 功效断言卡片（成分详情页）：断言 + 挂接的证据
export default function AssertionCard({ assertion: a }) {
  const ev = a.evidence || {}
  const t = TYPE_LABEL[ev.type] || { text: ev.type || '证据', cls: 'badge-muted' }
  const hasConc = a.effective_conc_low != null || a.effective_conc_high != null
  const concText = a.effective_conc_low === a.effective_conc_high
    ? `${a.effective_conc_low}%`
    : `${a.effective_conc_low ?? '?'}% – ${a.effective_conc_high ?? '?'}%`

  return (
    <div className="border border-line rounded-xl p-4 md:p-5 mb-4 hover:shadow-card transition-shadow">
      <div className="flex items-center gap-2.5 flex-wrap">
        <span className="text-[15px] font-bold bg-ok-soft text-ok px-3.5 py-1 rounded-full">{a.efficacy}</span>
        {hasConc && <span className="badge-brand">起效浓度 {concText}</span>}
      </div>
      {a.note && <p className="mt-2.5 text-[13px] text-ink-2">{a.note}</p>}

      <div className="mt-3 bg-bg rounded-[10px] px-4 py-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={t.cls}>{t.text}</span>
          <span className="text-[13px] font-semibold">{ev.title}</span>
        </div>
        <div className="text-xs text-ink-3 mt-1.5 flex flex-wrap gap-x-3">
          {ev.source && <span>{ev.source}</span>}
          {ev.year && <span>{ev.year} 年</span>}
          {ev.url && (
            <a href={ev.url} target="_blank" rel="noreferrer" className="text-brand hover:underline break-all">
              {ev.url.includes('pubmed') ? 'PubMed 原文 ↗' : '原文链接 ↗'}
            </a>
          )}
        </div>
        {ev.excerpt && <p className="text-xs text-ink-2 mt-2 leading-relaxed">摘录：{ev.excerpt}</p>}
      </div>
    </div>
  )
}
