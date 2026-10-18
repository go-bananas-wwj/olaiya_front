import { useEffect,useRef,useState } from 'react'
import { X,Plus,ArrowSquareOut,ArrowsLeftRight,CaretDown } from '@phosphor-icons/react'
import { api } from '../../api'
import { useResource } from '../useResource'
import { ProductPhoto,productPhotos } from '../ReferencePrimitives'
import PriceInfo from '../../components/PriceInfo'
import { DIRECTIONS,LEVELS,TYPES,ingredientName } from '../labels.mjs'
import { statusText } from './space.mjs'
import RelatedProducts from './RelatedProducts'
export function ResponsivePanel({name,narrow,onClose,children}) {
 const dialog=useRef(null)
 useEffect(()=>{if(narrow)dialog.current?.showModal()},[narrow])
 return narrow?<dialog ref={dialog} className="space-sheet" aria-label={name} onClose={onClose}>{children}</dialog>:<aside className="space-side-panel" aria-label={name}>{children}</aside>
}
export default function ProductPanel({item,narrow,comparison,scale,onAdd,onClose,onSource,onSimilar,related,basis,onBasis,onChoose,onCompare,onStartCompare}) {
 const product=useResource(()=>api.product(item.id),[item.id]),profile=useResource(()=>api.productCapabilityProfile(item.id),[item.id])
 const [tab,setTab]=useState('related'),[family,setFamily]=useState(null)
 const section=useRef(null),d=profile.data?.dimensions.find(d=>d.canonical===family)
 useEffect(()=>{if(family&&d){const f=requestAnimationFrame(()=>section.current?.scrollIntoView({block:'nearest'}));return()=>cancelAnimationFrame(f)}},[family,d])
 const photo=productPhotos[String(item.id)],hasPhoto=photo&&photo.source_page===item.source_url
 const added=comparison.includes(item.id),full=comparison.length>=2
 function openSource(c){onSource({ingredientId:c.ingredient_id,contribution:c,family,side:'所选产品',productName:item.name})}
 return <aside className={`space-side-panel fresh-inspector ${narrow?'is-mobile':''}`} aria-label="产品详情">
  <div className="inspector-kicker"><span><i/>当前参照产品</span><button type="button" aria-label="关闭产品详情" onClick={onClose}><X size={16}/></button></div>
  <div className="inspector-identity">{hasPhoto&&<ProductPhoto product={product.data||item} side="" mini/>}<div><p>{item.brand}</p><h2 aria-label={item.name} title={item.name}>{item.name.split('（')[0].replace(/^SkinCeuticals (?:Prevent )?/,'').replace(/® With.*$/,'')}</h2><span>{item.ingredient_count} 项成分 · {item.evidence_ingredient_count} 项有计分依据</span></div></div>
  <div className="inspector-actions"><button type="button" className="space-primary" onClick={()=>onStartCompare(item.id)}><ArrowsLeftRight size={15}/>与另一款对比</button><button type="button" className="inspector-add" disabled={added||full} onClick={()=>onAdd(item.id)}>{added?'已加入':<><Plus size={15}/>加入对比</>}</button></div>
  <div className="inspector-tabs" role="group" aria-label="产品探索内容"><button type="button" aria-pressed={tab==='related'} onClick={()=>setTab('related')}>找相近产品</button><button type="button" aria-pressed={tab==='evidence'} onClick={()=>setTab('evidence')}>看八维证据</button></div>
  {tab==='related'?<RelatedProducts item={item} state={related} basis={basis} onBasis={onBasis} onChoose={onChoose} onCompare={onCompare}/>:<>
   <section className="space-profile" aria-label="八方向成分证据画像"><div className="space-section-title"><h3>八个方向，看成分证据</h3><small>原始参考指数</small></div>{profile.loading?<p role="status" className="space-caption">正在读取证据画像…</p>:profile.error?<p role="alert">{profile.error}</p>:<>{DIRECTIONS.map(name=>{const row=profile.data.dimensions.find(d=>d.canonical===name),known=Number.isFinite(row?.score);return <button type="button" key={name} className={`space-profile-row ${family===name?'is-active':''}`} aria-label={`查看${name}的贡献成分`} aria-expanded={family===name} onClick={()=>setFamily(family===name?null:name)}><span>{name}</span><span className="space-profile-track"><i style={{width:known?`${row.score/scale*100}%`:'0%'}}/></span><strong>{known?row.score.toFixed(2):statusText(row?.status)}</strong><CaretDown size={12}/></button>})}<p className="space-caption">全库共用刻度 0–{scale.toFixed(2)}。指数汇总已收录资料，不是成品实测效果。</p></>}</section>
   {d&&<section ref={section} className="space-panel-contributions" aria-label={`${family}的贡献成分`}><h3>{family} · 贡献成分</h3><p className="space-caption">{d.ingredient_count} 个成分 · {d.source_count} 个来源</p>{d.contributions.length?d.contributions.slice(0,3).map(c=><article key={c.ingredient_id}><div><strong>{ingredientName(c)}</strong><span>+{c.weight.toFixed(2)}</span></div><p>{c.reference_only?TYPES.book:LEVELS[c.evidence_level]||'未明确分级'}</p><p>{c.concentration.label}</p><button type="button" onClick={()=>openSource(c)}>查看来源 <ArrowSquareOut size={12}/></button></article>):<p className="space-caption">{statusText(d.status)}，不将缺失资料写成零分。</p>}{d.contributions.length>3&&<details><summary>展开其余 {d.contributions.length-3} 个成分</summary>{d.contributions.slice(3).map(c=><article key={c.ingredient_id}><strong>{ingredientName(c)} · +{c.weight.toFixed(2)}</strong><p>{c.concentration.label}</p><button type="button" onClick={()=>openSource(c)}>查看来源 <ArrowSquareOut size={12}/></button></article>)}</details>}</section>}
  </>}
  <details className="inspector-details"><summary>产品资料与完整成分表</summary>{product.loading?<p>资料加载中…</p>:product.error?<p role="alert">{product.error}</p>:<><PriceInfo product={product.data}/>{product.data.source_url&&<a href={product.data.source_url} target="_blank" rel="noreferrer">产品与成分来源 <ArrowSquareOut size={12}/></a>}<div className="space-full-ingredients">{product.data.ingredients.map((i,n)=><button type="button" key={`${i.ingredient_id}-${n}`} onClick={()=>onSource({ingredientId:i.ingredient_id})}>{ingredientName(i)}<small>{i.position==null?'未知位次':`来源位次 #${i.position}`}</small></button>)}</div></>}</details>
 </aside>
}
