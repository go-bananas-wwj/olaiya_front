const EPS=1e-6
export const clampScore=score=>Math.max(-1,Math.min(1,score))
export const similarityRadius=threshold=>Math.sqrt(Math.max(0,2*(1-clampScore(threshold)))+2*EPS)
export const withinSimilarity=(score,threshold)=>Number.isFinite(score)&&clampScore(score)>=clampScore(threshold)-EPS
export function radialUniverse(source,selected,rows,mode='composition',dimensions=3){
 const scores=new Map(rows.map(p=>[p.id,p])),known=new Set(source.points.map(p=>p.product.id))
 const pointsWithLayout=[...source.points,...(source.catalogProducts||[]).filter(p=>!known.has(p.id)).map(product=>({product,position:[0,0,0],noProjection:true}))]
 const reference=pointsWithLayout.find(p=>p.product.id===selected)
 if(!reference)return {...source,points:[],byId:new Map()}
 const points=pointsWithLayout.filter(p=>p.product.id===selected||scores.has(p.product.id)).map(point=>{
  const row=scores.get(point.product.id),score=mode==='evidence'?1-row?.distance:row?.score
  const radius=point.product.id===selected?0:mode==='evidence'?Math.max(0,row.distance):Math.sqrt(2*(1-clampScore(score)))
  let direction=point.position.map((v,i)=>dimensions===2&&i===2?0:v-reference.position[i]),length=Math.hypot(...direction)
  if(length<1e-12||point.noProjection||reference.noProjection){const a=point.product.id*2.3999632297,z=Math.sin(point.product.id*1.618)*.9,s=Math.sqrt(1-z*z);direction=dimensions===2?[Math.cos(a),Math.sin(a),0]:[Math.cos(a)*s,Math.sin(a)*s,z];length=1}
  return {...point,position:direction.map(v=>v/length*radius),semantic_radius:radius}
 })
 const present=new Set(points.map(p=>p.product.id))
 return {...source,points,missingIds:source.missingIds.filter(id=>!present.has(id)),byId:new Map(points.map(p=>[p.product.id,p]))}
}
// Explicit attribute projection, separate from the semantic UMAP/PCA overview.
// Every need shares the same count/index scale; missing evidence has its own rail.
export function needPlane(source,need='需求'){
 const products=source.catalogProducts||source.points.map(p=>p.product)
 const maxCount=Math.max(1,...products.map(p=>Number.isFinite(p.ingredient_count)?p.ingredient_count:0))
 const maxScore=Math.max(1,...products.flatMap(p=>(p.scores||[]).filter(Number.isFinite)))
 const needAxes={need,xLabel:'已收录成分数（项）',yLabel:`${need}成分证据指数`,xMax:Math.max(20,Math.ceil(maxCount/20)*20),yMax:Math.max(1,Math.ceil(maxScore/4)*4),x0:-1.8,x1:1.8,y0:-1.3,y1:1.3,missingY:-2.15}
 const a=needAxes,points=source.points.map(p=>{const score=p.product.need_score,count=Number.isFinite(p.product.ingredient_count)?p.product.ingredient_count:0,missing=!Number.isFinite(score)
  return {...p,need_missing:missing,position:[a.x0+count/a.xMax*(a.x1-a.x0),missing?a.missingY:a.y0+score/a.yMax*(a.y1-a.y0),0]}
 })
 return {...source,needAxes,points,byId:new Map(points.map(p=>[p.product.id,p]))}
}
export function needStatus(product,index,need){return Number.isFinite(product.scores?.[index])?'evidence':product.declared_directions?.includes(need)?'declared':'unknown'}
export function needCounts(products,index,need){const counts={evidence:0,declared:0,unknown:0};for(const p of products)counts[needStatus(p,index,need)]++;return counts}
