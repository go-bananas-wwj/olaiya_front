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
