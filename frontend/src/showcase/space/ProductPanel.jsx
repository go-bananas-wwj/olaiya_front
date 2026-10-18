import { useEffect, useRef, useState } from 'react'
import { ArrowRight, X, Plus, ArrowSquareOut } from '@phosphor-icons/react'
import { api } from '../../api'
import { useResource } from '../useResource'
import { ProductPhoto } from '../ReferencePrimitives'
import PriceInfo from '../../components/PriceInfo'
import { DIRECTIONS, LEVELS, TYPES, ingredientName } from '../labels.mjs'
import { statusText } from './space.mjs'

export function ResponsivePanel({ name, narrow, onClose, children }) {
  const dialog=useRef(null)
  useEffect(()=>{if(narrow)dialog.current?.showModal()},[narrow])
  return narrow?<dialog ref={dialog} className="space-sheet" aria-label={name} onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)e.currentTarget.close()}}>{children}</dialog>
    :<aside className="space-side-panel" aria-label={name}>{children}</aside>
}

export default function ProductPanel({ item, narrow, comparison, scale, onAdd, onClose, onSource, onSimilar }) {
  const product=useResource(()=>api.product(item.id),[item.id])
  const profile=useResource(()=>api.productCapabilityProfile(item.id),[item.id])
  const [family,setFamily]=useState(null)
  const contributionSection=useRef(null)
  const d=profile.data?.dimensions.find(d=>d.canonical===family)
  useEffect(()=>{
    if(!family||!d)return
    const frame=requestAnimationFrame(()=>contributionSection.current?.scrollIntoView({block:'nearest'}))
    return()=>cancelAnimationFrame(frame)
  },[family,d])
  const max=scale
  const added=comparison.includes(item.id),full=comparison.length>=2
  return <ResponsivePanel name="产品详情" narrow={narrow} onClose={onClose}>
    <div className="space-panel-header"><span>产品详情</span><button type="button" aria-label="关闭产品详情" onClick={onClose}><X size={18}/></button></div>
    <div className="space-product-identity"><div><p>{item.brand}</p><h2>{item.name}</h2></div>{product.data&&<ProductPhoto product={product.data} side="" mini/>}</div>
    <button type="button" className="space-primary space-add" disabled={added||full} onClick={()=>{onAdd(item.id);if(narrow)onClose()}}>{added?'已加入对比':full?'对比位已满':<><Plus size={15}/>加入对比</>}</button>
    {full&&!added&&<p className="space-caption">先在底部移除一款，再加入此产品。</p>}
    <div className="space-record-counts"><span><b>{item.ingredient_count}</b>列出成分</span><span><b>{item.evidence_ingredient_count}</b>可计分成分</span><span><b>{item.source_count}</b>收录来源</span></div>
    <section className="space-profile" aria-label="八方向成分证据画像"><div className="space-section-title"><h3>八个方向，看成分证据</h3><small>原始参考指数</small></div>
      {profile.loading?<p role="status" className="space-caption">正在读取证据画像…</p>:profile.error?<p role="alert" className="space-error">证据暂未读取：{profile.error}</p>:<>
        {DIRECTIONS.map(name=>{const row=profile.data.dimensions.find(d=>d.canonical===name);const known=Number.isFinite(row?.score)
          return <button type="button" key={name} className={`space-profile-row ${family===name?'is-active':''}`} aria-label={`查看${name}的贡献成分`} aria-expanded={family===name} onClick={()=>setFamily(family===name?null:name)}>
            <span>{name}</span><span className="space-profile-track"><i style={{width:known?`${row.score/max*100}%`:'0%'}}/></span><strong>{known?row.score.toFixed(2):statusText(row?.status)}</strong><ArrowRight size={12}/>
          </button>})}
        <p className="space-caption">全库八方向共用刻度 0–{max.toFixed(2)}；指数不是成品实测效果。可加入两款并排核对。</p>
      </>}
    </section>
    {d&&<section ref={contributionSection} className="space-panel-contributions" aria-label={`${family}的贡献成分`}><h3>{family} · 贡献成分</h3><p className="space-caption">{d.ingredient_count} 个成分 · {d.source_count} 个去重来源</p>
      {d.contributions.length? <>
        {d.contributions.slice(0,3).map(c=><article key={c.ingredient_id}><div><strong>{ingredientName(c)}</strong><span>+{c.weight.toFixed(2)}</span></div><p>{c.reference_only?TYPES.book:LEVELS[c.evidence_level]||'未明确分级'}</p><p>{c.concentration.label}</p><button type="button" onClick={()=>onSource({ingredientId:c.ingredient_id,contribution:c,family,side:'所选产品'})}>查看来源 <ArrowSquareOut size={11}/></button></article>)}
        {d.contributions.length>3&&<details><summary>展开其余 {d.contributions.length-3} 个成分</summary>{d.contributions.slice(3).map(c=><article key={c.ingredient_id}><strong>{ingredientName(c)} · +{c.weight.toFixed(2)}</strong><p>{c.concentration.label}</p><button type="button" onClick={()=>onSource({ingredientId:c.ingredient_id,contribution:c,family,side:'所选产品'})}>查看来源 <ArrowSquareOut size={11}/></button></article>)}</details>}
      </>:<p className="space-caption">{statusText(d.status)}，不将缺失资料写成零分。</p>}
    </section>}
    <section className="space-product-more"><h3>资料与来源</h3>{product.loading?<p role="status" className="space-caption">产品资料加载中…</p>:product.error?<p role="alert" className="space-error">{product.error}</p>:<>
      <PriceInfo product={product.data}/>
      {product.data.source_url&&<a href={product.data.source_url} target="_blank" rel="noreferrer">产品成分来源 <ArrowSquareOut size={12}/></a>}
      <details><summary>完整成分表 · {product.data.ingredients.length} 项记录</summary><div className="space-full-ingredients">{product.data.ingredients.map((ing,i)=><button key={`${ing.ingredient_id}-${i}`} type="button" onClick={()=>onSource({ingredientId:ing.ingredient_id})}>{ingredientName(ing)}<small>{ing.position==null?'未知位次':`来源位次 #${ing.position}`}</small></button>)}</div></details>
    </>}
    <button type="button" className="space-similar-link" onClick={()=>onSimilar(item)}>按原始向量找相似 <ArrowRight size={14}/></button>
    </section>
  </ResponsivePanel>
}
