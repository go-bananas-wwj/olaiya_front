const fold = s => String(s || '').toLowerCase().replace(/[\s\p{P}\p{S}]/gu, '')
export function matchingProducts(products,query='') {
  const q=fold(query)
  return q ? products.filter(p=>[p.name,p.brand,p.nmpa_id].some(v=>fold(v).includes(q))) : products
}
export function coordinatesFor(product,mode,axes) {
  if(mode==='semantic') return Array.isArray(product.coordinates)&&product.coordinates.length===2&&product.coordinates.every(Number.isFinite)?product.coordinates:null
  const xy=axes.map(i=>product.scores[i])
  return xy.every(Number.isFinite)?xy:null
}
export function boundsFor(points,mode) {
  if(!points.length)return {x:[0,1],y:[0,1]}
  const result={}
  for(const [i,key] of ['x','y'].entries()){
    let low=mode==='axes'?0:Math.min(...points.map(p=>p[i])),high=Math.max(...points.map(p=>p[i]))
    if(high===low){low=mode==='axes'?0:low-.5;high=high+.5}
    result[key]=[low,high||1]
  }
  return result
}
export function hitsAt(points,x,y,radius=10) {
  return points.map(p=>({...p,distance:(p.x-x)**2+(p.y-y)**2})).filter(p=>p.distance<=radius**2)
    .sort((a,b)=>a.distance-b.distance||a.product.id-b.product.id).map(p=>p.product)
}
export function addComparison(ids,id){return ids.includes(id)||ids.length>=2?ids:[...ids,id]}
export function pointTone(value,max=1){
  if(!Number.isFinite(value))return '#ccd7cf'
  const t=Math.max(0,Math.min(1,value/(max||1)))
  const from=[139,201,177],to=[31,130,104]
  return `rgb(${from.map((v,i)=>Math.round(v+(to[i]-v)*t)).join(',')})`
}
export const statusText = s => s==='unrated'?'资料未明确评级':'暂无合格资料'

// Aggregated markers are exact screen-space groups, never moved product coordinates.
export function groupScreenPoints(points,cell=36,excluded=new Set()) {
  const buckets=new Map()
  for(const p of points){
    if(excluded.has(p.product.id))continue
    const key=`${Math.floor(p.x/cell)}:${Math.floor(p.y/cell)}`
    if(!buckets.has(key))buckets.set(key,[])
    buckets.get(key).push(p)
  }
  const groups=[...buckets.values()].map(group=>({
    x:group.reduce((s,p)=>s+p.x,0)/group.length,
    y:group.reduce((s,p)=>s+p.y,0)/group.length,
    count:group.length,items:group.map(p=>p.product).sort((a,b)=>a.id-b.id),
    radius:group.length===1?5.5:Math.min(15,10+Math.log2(group.length+1)*.8),
  }))
  // Merge colliding group badges using the exact weighted centroid. This changes
  // only the view's aggregation, never a product's frozen data coordinates.
  for(let round=0;round<6;round++){
    let changed=false
    for(let i=0;i<groups.length;i++)for(let j=i+1;j<groups.length;j++){
      const a=groups[i],b=groups[j]
      if(Math.hypot(a.x-b.x,a.y-b.y)>=a.radius+b.radius+3)continue
      const count=a.count+b.count
      groups[i]={x:(a.x*a.count+b.x*b.count)/count,y:(a.y*a.count+b.y*b.count)/count,
        count,items:[...a.items,...b.items].sort((a,b)=>a.id-b.id),radius:Math.min(15,10+Math.log2(count+1)*.8)}
      groups.splice(j,1);j--;changed=true
    }
    if(!changed)break
  }
  return groups
}
