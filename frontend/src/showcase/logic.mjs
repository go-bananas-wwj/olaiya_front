export function sortCandidates(rows, sort, targetUnit) {
  if (sort !== 'price' || !targetUnit) return [...rows]
  const price = row => row.unit_price_unit === targetUnit && Number.isFinite(row.unit_price)
    ? row.unit_price : Infinity
  return [...rows].sort((a, b) => price(a) - price(b))
}

export function compareIngredients(target = [], candidate = []) {
  const a = new Set(target.map(i => i.ingredient_id))
  const b = new Set(candidate.map(i => i.ingredient_id))
  return {
    shared: target.filter(i => b.has(i.ingredient_id)),
    onlyTarget: target.filter(i => !b.has(i.ingredient_id)),
    onlyCandidate: candidate.filter(i => !a.has(i.ingredient_id)),
  }
}

export function chartScale(profiles) {
  const scores = profiles.flatMap(p => (p?.dimensions || []).map(d => d.score)).filter(Number.isFinite)
  return Math.max(1, Math.ceil(Math.max(0, ...scores) * 2) / 2)
}

export function comparableUnitPrices(a, b) {
  return Boolean(a && b && ['ml', 'g'].includes(a.unit_price_unit) && a.unit_price_unit === b.unit_price_unit
    && Number.isFinite(a.unit_price) && a.unit_price >= 0 && Number.isFinite(b.unit_price) && b.unit_price >= 0)
}

export function ingredientRows(a = [], b = [], view = 'differences') {
  const left = new Map(a.map(i => [i.ingredient_id, i]))
  const right = new Map(b.map(i => [i.ingredient_id, i]))
  return [...new Set([...left.keys(), ...right.keys()])].map(id => ({
    ...(left.get(id) || right.get(id)), a: left.get(id), b: right.get(id),
  })).filter(row => view === 'all' || (view === 'shared' ? row.a && row.b : !row.a || !row.b))
}
