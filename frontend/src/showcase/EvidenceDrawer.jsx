import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

const TYPES = { paper: '论文', database: '数据库功能分类（非功效实证）', regulation: '法规（非功效实证）', patent: '专利（未经同行评议）', supplier: '供应商（未经同行评议）', book: '工具书（行业参考）' }
const LEVELS = { human_rct: '人体随机对照研究', human_ct: '消费者测试', human_open: '人体开放／观察研究', in_vitro: '体外研究', animal: '动物研究', oral: '口服研究', review: '综述', regulation: '法规资料（非功效实证）', unknown: '未明确分级' }

export default function EvidenceDrawer({ ingredientId, onClose }) {
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
  return (
    <dialog ref={dialog} aria-label="成分证据" className="showcase-drawer" onClose={onClose}
      onClick={e => { if (e.target === e.currentTarget) e.currentTarget.close() }}>
      <div className="flex justify-between gap-4 items-start">
        <div><p className="text-xs text-pearl-ink-3">可追溯资料</p><h2 className="font-display text-2xl mt-2">{data?.cn_name || data?.inci_name || '成分证据'}</h2></div>
        <button type="button" className="btn-page" onClick={() => dialog.current.close()}>关闭</button>
      </div>
      {state.loading && <p role="status" className="mt-6">资料加载中…</p>}
      {state.error && <p role="alert" className="pearl-notice mt-6">资料加载失败：{state.error}</p>}
      {data && <>
        <p className="text-xs text-pearl-ink-3 mt-2 break-words">{data.inci_name}</p>
        <p className="pearl-notice mt-5">成分资料不等同于成品功效验证。功能分类、法规与安全评估不是临床功效实证；未收录资料不代表没有研究。</p>
        {!data.assertions.length && <p className="text-sm">暂未收录该成分的关联证据，不作功效判断。</p>}
        {data.assertions.map((a, i) => <article key={i} className="border-t border-line py-4">
          <p className="text-xs text-iris">{TYPES[a.evidence?.type] || `资料类型：${a.evidence?.type || '未知'}`}</p>
          <h3 className="font-semibold mt-2">{a.efficacy}</h3>
          <p className="text-xs mt-2 text-pearl-ink-2">证据层级：{LEVELS[a.evidence_level] || '未明确分级，以研究条件与备注为准'}</p>
          {a.evidence?.url ? <a className="block text-sm text-iris underline mt-2 break-words" href={a.evidence.url} target="_blank" rel="noreferrer">{a.evidence.title} ↗</a>
            : <p className="text-sm mt-2">{a.evidence?.title || '未记录标题'}</p>}
          <p className="text-xs text-pearl-ink-3 mt-2">{a.evidence?.source}{a.evidence?.year ? ` · ${a.evidence.year}` : ''}</p>
          {a.note && <p className="text-sm mt-3 whitespace-pre-wrap">{a.note}</p>}
          {(a.effective_conc_low != null || a.effective_conc_high != null) && <p className="text-xs mt-3 text-pearl-ink-3">文献研究浓度：{a.effective_conc_low ?? '未知'}% – {a.effective_conc_high ?? '未知'}%；适用条件见原文，不能直接视为本产品的有效浓度。</p>}
        </article>)}
      </>}
    </dialog>
  )
}
