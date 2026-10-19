export function distanceFromCosine(score,metric='cosine') {
  if(!Number.isFinite(score))return null
  const cosine=Math.max(-1,Math.min(1,score))
  return metric==='euclidean'?Math.sqrt(2*(1-cosine)):1-cosine
}
export function pairForReference(id,pair={a:9,b:73}) {
  return {a:id,b:pair.b===id?pair.a:pair.b}
}
export function projectionAvailable(data,algorithm,dimensions) {
  const p=data?.projection
  if(algorithm==='pca')return p?.pca?.status==='ready'
  return dimensions===3?p?.umap_3d?.status==='ready':p?.status==='ready'
}
export function projectionVariance(data,axisOrder,dimensions) {
  const ratios=data?.projection?.pca?.explained_variance_ratio
  if(!Array.isArray(ratios))return null
  return Math.round(axisOrder.slice(0,dimensions).reduce((sum,index)=>sum+(ratios[index]||0),0)*10000)/100
}
// Version/source suffixes are part of the identity, not expendable subtitles.
export const shortName=name=>String(name||'').replace(/^SkinCeuticals\s+/i,'').trim()
export function projectionQuality(data,algorithm,dimensions) {
  if(algorithm==='pca')return dimensions===3?data?.projection?.pca?.quality:null
  return dimensions===3?data?.projection?.umap_3d?.quality:data?.projection?.quality
}
