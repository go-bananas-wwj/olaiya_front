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
  if(!Number.isFinite(value))return '#7d828b'
  const t=Math.max(0,Math.min(1,value/(max||1)))
  const from=[139,129,166],to=[91,63,171]
  return `rgb(${from.map((v,i)=>Math.round(v+(to[i]-v)*t)).join(',')})`
}
export const statusText = s => s==='unrated'?'资料未明确评级':'暂无合格资料'
