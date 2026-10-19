import { distanceFromCosine } from './projectorLogic.mjs'
import { coordinatesFor } from './projectorGeometry.mjs'

export function modeDistance(product, mode, metric = 'cosine') {
  if (mode === 'evidence') return Number.isFinite(product.distance) && product.distance >= 0 ? product.distance : null
  return distanceFromCosine(product.score, metric)
}
export const distanceLabel = (mode, metric = 'cosine') => mode === 'evidence' ? '八方向证据距离' : metric === 'cosine' ? '余弦距离' : '归一化欧氏距离'

export function modeNeighbors(data, lookup, selected, mode) {
  if (!data || data.product_id !== selected) return []
  const rows = mode === 'evidence' ? (data.available ? data.items : []) : data.similar
  const seen = new Set([selected])
  return (rows || []).filter(p => {
    if (!lookup.has(p.id) || seen.has(p.id)) return false
    seen.add(p.id)
    return true
  }).map(p => ({ ...lookup.get(p.id), score: p.score, distance: p.distance }))
}
export function visibleCount(products, algorithm, dimensions, isolated, selected, neighbors, axes = [0, 1, 2]) {
  const visible = isolated ? new Set([selected, ...neighbors.map(p => p.id)]) : null
  return products.filter(p => (!visible || visible.has(p.id)) && coordinatesFor(p, algorithm, dimensions, axes)).length
}
