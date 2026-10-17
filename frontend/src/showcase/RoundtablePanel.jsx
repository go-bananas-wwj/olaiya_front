import { useEffect, useRef, useState } from 'react'
import { streamRoundtable } from './stream.mjs'

const ROLES = { ingredient_expert: '成分专家', regulation_officer: '法规合规官', evidence_verifier: '文献核验官', dose_analyst: '剂量推断师' }

export default function RoundtablePanel({ target, candidate }) {
  const [state, setState] = useState({ phase: 'idle', speeches: [] })
  const request = useRef(null)
  useEffect(() => () => request.current?.abort(), [])

  async function start(product) {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    let failed = false
    let hasVerdict = false
    setState({ phase: 'running', product, speeches: [] })
    try {
      const result = await streamRoundtable(product.name, controller.signal, event => {
        if (controller.signal.aborted) return
        if (event.event === 'speak') setState(s => ({ ...s, speeches: [...s.speeches, event] }))
        if (event.event === 'verdict') {
          hasVerdict = true
          setState(s => ({ ...s, verdict: event }))
        }
        if (event.event === 'error') {
          failed = true
          // Internal gateway errors may contain endpoints; keep product copy simple.
          setState(s => ({ ...s, phase: 'error', error: '圆桌暂不可用：云模型未配置、服务不可达或调用失败。成分和价格对照仍可使用。' }))
        }
      }, product.id)
      if (controller.signal.aborted || failed) return
      if (result !== 'done' || !hasVerdict) throw new Error('连接中断：未收到完整结论，请重试。')
      setState(s => ({ ...s, phase: 'done' }))
    } catch (error) {
      if (controller.signal.aborted) return
      setState(s => ({ ...s, phase: 'error', error: error.message.startsWith('连接中断') ? error.message : '圆桌连接失败，请稍后重试。' }))
    }
  }
  const assertions = state.verdict?.evidence?.ingredient_evidence?.assertions || []
  return <section className="glass-card" aria-label="圆桌解释">
    <div className="showcase-section-head"><div><h2 className="pearl-title">让圆桌解释证据</h2><p className="text-sm text-pearl-ink-2">分别核对每款产品的资料；模型从工具事实中选择重点，不把相似度当作功效结论。</p></div></div>
    <div className="flex flex-wrap gap-3 mt-5">
      <button className="btn-fairy" disabled={!target} onClick={() => start(target)}>核验参照产品</button>
      <button className="btn-fairy-ghost" disabled={!candidate} onClick={() => start(candidate)}>核验对照产品</button>
      {state.phase === 'running' && <button className="btn-page" onClick={() => { request.current?.abort(); setState(s => ({ ...s, phase: 'stopped' })) }}>停止讨论</button>}
    </div>
    {state.product && <p className="text-sm mt-5 break-words">本次对象：{state.product.brand} · {state.product.name}</p>}
    <div className="grid md:grid-cols-2 gap-3 mt-4" aria-live="polite">
      {state.speeches.map((s, i) => <article key={i} className="fairy-panel p-4"><h3 className="text-sm font-semibold text-iris">{ROLES[s.role] || s.role}</h3><p className="text-sm mt-2 whitespace-pre-wrap">{s.content}</p></article>)}
    </div>
    {state.phase === 'running' && <p className="text-sm text-pearl-ink-3 mt-4" role="status">正在读取资料并生成角色发言…</p>}
    {state.phase === 'stopped' && <p className="text-sm mt-4">讨论已停止，尚未形成完整结论。</p>}
    {state.error && <p className="pearl-notice mt-4" role="alert">{state.error}</p>}
    {state.phase === 'done' && <div className="fairy-panel p-5 mt-4">
      <h3 className="font-semibold">{state.verdict.label}</h3><p className="text-sm mt-2">{state.verdict.reason}</p>
      <p className="text-xs text-pearl-ink-3 mt-3">模型综合结论，仅依据本次资料；浓度与剂量判断为估计。</p>
      <details className="mt-4 text-sm"><summary>查看引用资料（{assertions.length} 条）</summary>
        {!assertions.length && <p className="mt-2">本次未返回可展开的引用资料。</p>}
        {assertions.map((a, i) => <article key={i} className="border-t border-line mt-3 pt-3"><p>{a.efficacy} · {a.evidence_level || '未明确分级'}</p>
          {a.evidence?.url && <a href={a.evidence.url} target="_blank" rel="noreferrer" className="text-iris underline">{a.evidence.title} ↗</a>}
          {a.note && <p className="text-xs mt-2">{a.note}</p>}</article>)}
      </details>
    </div>}
  </section>
}
