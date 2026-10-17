import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useResource } from './useResource'

export default function SimilarPicker({ targetId, referenceLabel = 'A', onSelect, onClose }) {
  const dialog = useRef(null)
  const [method, setMethod] = useState('overlap')
  const [limit, setLimit] = useState(3)
  useEffect(() => { dialog.current.showModal() }, [])
  const state = useResource(() => method === 'overlap'
    ? api.productSimilarLevels(targetId, { k: limit }).then(r => ({ items: r.l1 }))
    : api.productSimilar(targetId, { k: limit }).then(r => ({ items: r.similar || [], reason: r.reason })), [targetId, method, limit])
  return <dialog ref={dialog} className="showcase-drawer" aria-label="选择相似候选" onClose={onClose}>
    <div className="cap-drawer-heading"><div><p className="cap-eyebrow">以产品 {referenceLabel} 为参照</p><h2>选择相似候选</h2></div><button className="cap-text-button" onClick={() => dialog.current.close()}>关闭</button></div>
    <p className="cap-small-note">选择一款替换另一侧产品，回到功效证据对照。相似不代表功效等同。</p>
    <details className="cap-method"><summary>匹配说明</summary><label>匹配方式 <select aria-label="匹配方式" value={method} onChange={e => { setMethod(e.target.value); setLimit(3) }}>
      <option value="overlap">按成分重合</option><option value="embedding">按成分表语义</option></select></label>
      <p>{method === 'overlap' ? '成分集合的 Jaccard 重合，不考虑浓度。' : '预计算成分表向量的余弦相似度，不是功效或有效率。'}</p>
    </details>
    {state.loading && <p role="status">正在查找候选…</p>}
    {state.error && <p role="alert">候选读取失败：{state.error}</p>}
    {state.data?.reason && <p role="alert">{state.data.reason}，可切换为按成分重合。</p>}
    {state.data && !state.data.items.length && !state.data.reason && <p>暂无相似候选，可以直接搜索产品 B。</p>}
    <div className="cap-similar-list">{state.data?.items.map(p => <button type="button" key={p.id} onClick={() => onSelect(p.id)}>
      <small>{p.brand}</small><strong>{p.name}</strong>
      <span>共有 {p.shared} 项成分 · {p.price_current == null ? '暂无价格' : `参考价 ¥${p.price_current}`}{p.spec ? ` / ${p.spec}` : ''}</span>
    </button>)}</div>
    {limit === 3 && state.data?.items.length === 3 && <button type="button" className="cap-text-button cap-load-more" onClick={() => setLimit(12)}>查看更多候选</button>}
  </dialog>
}
