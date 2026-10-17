import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { TYPES, LEVELS } from './labels.mjs'

export default function EvidenceDrawer({ ingredientId, context, onClose }) {
  const dialog = useRef(null)
  const [state, setState] = useState({ loading: true })
  useEffect(() => {
    let current = true
    dialog.current.showModal()
    api.ingredient(ingredientId).then(data => {
      if (current) setState({ data })
    }).catch(error => { if (current) setState({ error: error.message }) })
    return () => { current = false }
  }, [ingredientId])
  const data = state.data
  const contribution = context?.contribution
  const percent = value => Number(value).toLocaleString('zh-CN', { maximumSignificantDigits: 4 })
  const verdicts = { effective: '区间达到研究下限', insufficient: '区间低于研究下限', uncertain: '区间跨越研究下限', trace_level: '微量段，仍需原料披露', unknown: '无法判断' }
  return (
    <dialog ref={dialog} aria-label="成分证据" className="showcase-drawer" onClose={onClose}
      onClick={e => { if (e.target === e.currentTarget) e.currentTarget.close() }}>
      <div className="flex justify-between gap-4 items-start">
        <div><p className="text-xs text-pearl-ink-3">{contribution ? `产品 ${context.side} · ${context.family} · 可追溯资料` : '可追溯资料'}</p><h2 className="font-display text-2xl mt-2">{data?.cn_name || contribution?.cn_name || data?.inci_name || '成分证据'}</h2></div>
        <button type="button" className="btn-page" onClick={() => dialog.current.close()}>关闭</button>
      </div>
      {contribution && <section className="cap-drawer-calculation">
        <h3>{context.excluded ? '未计入本指数的资料' : '本指数采用的证据'}</h3>
        <p>{context.excluded ? contribution.reason : `计算贡献：+${contribution.weight.toFixed(2)}；同一成分、同一方向只取最高合格权重。`}</p>
        <p>{TYPES[contribution.evidence.type]} · {LEVELS[contribution.evidence_level] || '未明确分级'}</p>
        {contribution.evidence.url ? <a href={contribution.evidence.url} target="_blank" rel="noreferrer">{contribution.evidence.title} ↗</a> : <p>{contribution.evidence.title}（未记录在线链接）</p>}
        <p>{contribution.evidence.source}{contribution.evidence.year ? ` · ${contribution.evidence.year}` : ''}</p>
        <p>{contribution.efficacy}</p>
        {contribution.note && <p>{contribution.note}</p>}
        {contribution.evidence.excerpt && <details><summary>查看来源摘录</summary><p>{contribution.evidence.excerpt}</p></details>}
        <p>{contribution.concentration.label}{contribution.concentration.low != null && `：${percent(contribution.concentration.low)}%–${percent(contribution.concentration.high)}%`}</p>
        {contribution.dose.research_available && <p>文献研究浓度：{percent(contribution.dose.research_low)}%{contribution.dose.research_high != null && `–${percent(contribution.dose.research_high)}%`}；适用条件见原文。</p>}
        {contribution.dose.assessable && <p>浓度对照：{verdicts[contribution.dose.verdict]}（参考，非成品验证）。</p>}
        <p>{contribution.dose.note}。浓度信息不改变本指数的证据权重。</p>
      </section>}
      {state.loading && <p role="status" className="mt-6">资料加载中…</p>}
      {state.error && <p role="alert" className="pearl-notice mt-6">资料加载失败：{state.error}</p>}
      {data && <>
        <p className="text-xs text-pearl-ink-3 mt-2 break-words">{data.inci_name}</p>
        <p className="pearl-notice mt-5">成分资料不等同于成品功效验证。功能分类、法规与安全评估不是临床功效实证；未收录资料不代表没有研究。</p>
        {!data.assertions.length && <p className="text-sm">暂未收录该成分的关联证据，不作功效判断。</p>}
        <details open={!contribution}><summary className="cap-other-sources">该成分的其他资料（不一定计入本指数）</summary>
        {data.assertions.map((a, i) => <article key={i} className="border-t border-line py-4">
          <p className="text-xs text-iris">{TYPES[a.evidence?.type] || `资料类型：${a.evidence?.type || '未知'}`}</p>
          <h3 className="font-semibold mt-2">{a.efficacy}</h3>
          <p className="text-xs mt-2 text-pearl-ink-2">证据层级：{LEVELS[a.evidence_level] || '未明确分级，以研究条件与备注为准'}</p>
          {a.evidence?.url ? <a className="block text-sm text-iris underline mt-2 break-words" href={a.evidence.url} target="_blank" rel="noreferrer">{a.evidence.title} ↗</a>
            : <p className="text-sm mt-2">{a.evidence?.title || '未记录标题'}</p>}
          <p className="text-xs text-pearl-ink-3 mt-2">{a.evidence?.source}{a.evidence?.year ? ` · ${a.evidence.year}` : ''}</p>
          {a.note && <p className="text-sm mt-3 whitespace-pre-wrap">{a.note}</p>}
          {(a.effective_conc_low != null || a.effective_conc_high != null) && <p className="text-xs mt-3 text-pearl-ink-3">文献研究浓度：{a.effective_conc_low ?? '未知'}% – {a.effective_conc_high ?? '未知'}%；适用条件见原文，不能直接视为本产品的有效浓度。</p>}
        </article>)}</details>
      </>}
    </dialog>
  )
}
