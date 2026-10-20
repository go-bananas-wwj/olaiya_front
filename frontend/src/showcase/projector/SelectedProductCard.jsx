import {useEffect,useRef,useState} from 'react'
import {X,CaretDown,CaretUp,ArrowsLeftRight,ArrowSquareOut,ImageSquare} from '@phosphor-icons/react'
import {productPhotos} from '../ReferencePrimitives'
import {ingredientName} from '../labels.mjs'

export default function SelectedProductCard({item,state,expanded,onExpand,onClear,onEvidence,onCompare,onIngredient,onLayout,evidenceMode}){
 const card=useRef(null),[imageFailed,setImageFailed]=useState(false)
 const product=state.data?.id===item.id?state.data:null,media=product?.presentation
 const local=productPhotos[String(item.id)],image=product&&local?.source_page===product.source_url?local.src:media?.image_url
 useEffect(()=>setImageFailed(false),[item.id,image])
 useEffect(()=>{const observer=new ResizeObserver(()=>onLayout?.());observer.observe(card.current);return()=>observer.disconnect()},[onLayout])
 const seen=new Set(),ingredients=(product?.ingredients||[]).filter(i=>{if(seen.has(i.ingredient_id))return false;seen.add(i.ingredient_id);return true})
 const claims=[...new Set((product?.claims||[]).map(c=>c.claim).filter(Boolean))]
 function ingredient(i,n){return <button type="button" key={`${i.ingredient_id}-${n}`} aria-label={`查看成分 ${ingredientName(i)}`} title={i.position==null?'未知位次':`来源位次 #${i.position}`} onClick={()=>onIngredient(i.ingredient_id)}>{ingredientName(i)}</button>}
 return <section ref={card} className={`projector-info projector-preview ${expanded?'is-expanded':'is-compact'}`} data-testid="projector-info" data-product-id={item.id} aria-label="所选产品资料">
  <button type="button" className="projector-preview-close" aria-label="取消选中产品" title="取消选择并返回全景" onClick={onClear}><X size={16}/></button>
  <div className="projector-preview-hero">
   <div className="projector-preview-photo">{image&&!imageFailed?<img key={image} src={image} alt={`${item.brand} ${item.name}参考图`} referrerPolicy="no-referrer" onError={()=>setImageFailed(true)}/>:<span><ImageSquare size={27}/>{state.loading?'读取图片…':imageFailed?'图片暂不可用':'图片未收录'}</span>}</div>
   <div className="projector-preview-identity"><p>{item.brand||'品牌未记录'}</p><button type="button" className="projector-info-heading" aria-expanded={expanded} onClick={onExpand}><strong title={item.name}>{item.name}</strong>{expanded?<CaretUp size={15}/>:<CaretDown size={15}/>}</button>{product?.spec&&<span>{product.spec}{product.price_current!=null?` · 参考价 ¥${product.price_current}`:''}</span>}</div>
  </div>
  {state.loading?<p className="projector-preview-status" role="status">正在读取产品介绍与成分…</p>:state.error?<p className="projector-preview-status" role="alert">资料加载失败：{state.error}</p>:<>
   {media?.summary_excerpt&&<section className={`projector-preview-description ${expanded?'is-expanded':''}`}><h3>来源页简介 <small>社区来源</small></h3><p>{media.summary_excerpt}{media.summary_truncated?'…':''}</p></section>}
   <section className="projector-preview-claims" aria-label="产品功效宣称"><h3>功效宣称 <small>来源记录</small></h3>{claims.length?<div>{claims.slice(0,expanded?claims.length:3).map(c=><span key={c}>{c}</span>)}{!expanded&&claims.length>3&&<button type="button" onClick={onExpand}>查看全部 {claims.length} 项</button>}</div>:<p>暂未收录产品功效宣称</p>}</section>
   {<section className="projector-preview-ingredients"><h3>已收录成分 <small>{ingredients.length} 项</small></h3><div>{ingredients.slice(0,expanded?8:3).map(ingredient)}</div>{expanded&&ingredients.length>8&&<details onToggle={onLayout}><summary>查看全部 {ingredients.length} 项成分</summary><div>{ingredients.slice(8).map(ingredient)}</div></details>}{!ingredients.length&&<p>成分资料未收录</p>}</section>}
   {evidenceMode&&item.eligible===false&&<p className="projector-coverage-warning">未进入此地图：{item.missing_directions?.join('、')}资料不足。</p>}
  </>}
  <div className="projector-info-actions"><button type="button" onClick={onEvidence}>成分与证据</button><button type="button" onClick={onCompare}><ArrowsLeftRight size={13}/>两款对比</button></div>
  {product?.source_url&&<a className="projector-preview-source" href={product.source_url} target="_blank" rel="noreferrer">{media?'简介与参考图来源':'产品与成分来源'} <ArrowSquareOut size={12}/></a>}
 </section>
}
