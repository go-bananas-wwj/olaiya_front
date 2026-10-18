import { ArrowRight,ArrowsLeftRight,ArrowSquareOut } from '@phosphor-icons/react'
import { productPhotos,ProductPhoto } from '../ReferencePrimitives'
export default function RelatedProducts({item,state,basis,onBasis,onChoose,onCompare}) {
 const data=state.data
 return <section className="related-products" aria-label="相近产品"><div className="related-heading"><h3>找到相近的下一款</h3><span>候选 {data?.items?.length||0} 款</span></div>
  <div className="related-basis" role="group" aria-label="相近产品依据"><button type="button" aria-pressed={basis==='composition'} onClick={()=>onBasis('composition')}>成分组成接近</button><button type="button" aria-pressed={basis==='evidence'} onClick={()=>onBasis('evidence')}>功效证据接近</button></div>
  <p className="related-explanation">{basis==='composition'?'按原始成分表语义检索，地图连线标出真实候选。':'比较参照产品已有的证据方向，不为未知资料补零。'}</p>
  {state.loading?<p role="status" className="related-status">正在查找相近产品…</p>:state.error?<p role="alert" className="related-status">暂未读取候选：{state.error}</p>:data?.available===false?<p className="related-status">{data.reason||'当前资料不足以检索，可切换另一种依据。'}</p>:!data?.items?.length?<p className="related-status">暂未找到可比候选。可以搜索其他产品。</p>:<div className="related-list">{data.items.map((p,i)=>{
   const photo=productPhotos[String(p.id)],hasPhoto=photo&&photo.source_page===p.source_url
   return <article key={p.id} className="related-card"><div className="related-card-top"><span className="related-rank">{i+1}</span>{hasPhoto&&<ProductPhoto product={p} side="" mini/>}<button type="button" className="related-product-name" aria-label={`查看 ${p.name}`} onClick={()=>onChoose(p)}><small>{p.brand}</small><strong>{p.name.split('（')[0].replace(/^SkinCeuticals (?:Prevent )?/,'').replace(/® With.*$/,'')}</strong></button><ArrowRight size={14}/></div>
    <div className="related-card-bottom"><span>{basis==='evidence'?`可比 ${data.compared_directions?.length||0} 个方向`:`${p.evidence_ingredient_count??0}/${p.ingredient_count??0} 项成分有计分依据`}</span><button type="button" aria-label={`与${p.name}对比`} onClick={()=>onCompare(item.id,p.id)}>与它对比 <ArrowsLeftRight size={13}/></button></div>
   </article>
  })}</div>}
  <details className="related-method"><summary>匹配说明与局限</summary><p>{data?.note||'成分表向量用于寻找语义接近的候选，不代表配比相同或成品功效等同。二维距离不用于候选排序。'}</p>{basis==='evidence'&&data?.compared_directions?.length>0&&<p>本次可比方向：{data.compared_directions.join('、')}。候选必须覆盖以上全部方向；距离按全库共同尺度计算，不显示为功效百分比。</p>}</details>
 </section>
}
