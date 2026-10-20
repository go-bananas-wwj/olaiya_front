// Display-only axis expansion. Frozen projection coordinates and retrieval
// vectors remain unchanged. 2D price/evidence charts never use this transform.
export const DISPLAY_AXES = [1.12, 1.1, 2.1]
export function displayUniverse(source, dimensions) {
  if (dimensions !== 3) return source
  const points=source.points.map(point=>({...point,sourcePosition:point.position,position:point.position.map((v,i)=>v*DISPLAY_AXES[i])}))
  return {...source,points,byId:new Map(points.map(point=>[point.product.id,point]))}
}
export function depthCue(viewDepth, cameraDistance, dimensions=3) {
  if(dimensions!==3||!Number.isFinite(viewDepth)||!Number.isFinite(cameraDistance)||viewDepth<=0||cameraDistance<=0)return {scale:1,opacity:1}
  const scale=Math.max(.65,Math.min(1.55,cameraDistance/viewDepth))
  return {scale,opacity:Math.max(.55,Math.min(1,.4+.6*scale))}
}
