import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Loading, LoadError } from '../components/common'

// 单个产品选择器：下拉选择
function ProductPicker({ label, value, onChange, products, excludeId }) {
  return (
    <div className="flex-1 min-w-[220px]">
      <div className="kv-label mb-1.5">{label}</div>
      <select
        className="input"
        value={value}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">选择产品…</option>
        {products.filter((p) => p.id !== excludeId).map((p) => (
          <option key={p.id} value={p.id}>{p.brand} · {p.name}</option>
        ))}
      </select>
    </div>
  )
}

function IngredientRow({ ing, showEvidence }) {
  return (
    <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-line last:border-0 text-sm">
      <div className="min-w-0">
        {showEvidence && ing.has_evidence ? (
          <Link to={`/ingredients/${ing.ingredient_id}`} className="text-brand hover:underline font-medium">
            {ing.cn_name || ing.inci_name}
          </Link>
        ) : (
          <span>{ing.cn_name || ing.inci_name}</span>
        )}
      </div>
      <div className="flex gap-1.5 flex-shrink-0">
        {ing.is_active ? <span className="badge-brand">活性</span> : null}
        {ing.has_evidence && showEvidence ? <span className="badge-ok">有证据</span> : null}
      </div>
    </div>
  )
}

export default function Compare() {
  const [products, setProducts] = useState(null)
  const [listError, setListError] = useState(null)
  const [idA, setIdA] = useState(null)
  const [idB, setIdB] = useState(null)
  const [detailA, setDetailA] = useState(null)
  const [detailB, setDetailB] = useState(null)

  useEffect(() => {
    api.products().then(setProducts).catch((e) => setListError(e.message))
  }, [])

  useEffect(() => { setDetailA(null); if (idA) api.product(idA).then(setDetailA).catch(() => {}) }, [idA])
  useEffect(() => { setDetailB(null); if (idB) api.product(idB).then(setDetailB).catch(() => {}) }, [idB])

  const comparison = useMemo(() => {
    if (!detailA || !detailB) return null
    const mapB = new Map(detailB.ingredients.map((i) => [i.ingredient_id, i]))
    const mapA = new Map(detailA.ingredients.map((i) => [i.ingredient_id, i]))
    const shared = detailA.ingredients
      .filter((i) => mapB.has(i.ingredient_id))
      .map((i) => ({ ...i, has_evidence: i.has_evidence || mapB.get(i.ingredient_id).has_evidence }))
    const sharedIds = new Set(shared.map((i) => i.ingredient_id))
    const onlyA = detailA.ingredients.filter((i) => !sharedIds.has(i.ingredient_id))
    const onlyB = detailB.ingredients.filter((i) => !mapA.has(i.ingredient_id))
    return { shared, onlyA, onlyB }
  }, [detailA, detailB])

  if (listError) return <div className="card"><LoadError error={listError} /></div>
  if (!products) return <div className="card"><Loading /></div>

  return (
    <div>
      <div className="card">
        <h2 className="card-title">选择两款产品对比成分</h2>
        <div className="flex flex-col md:flex-row gap-4">
          <ProductPicker label="产品 A" value={idA ?? ''} onChange={setIdA} products={products} excludeId={idB} />
          <ProductPicker label="产品 B" value={idB ?? ''} onChange={setIdB} products={products} excludeId={idA} />
        </div>
      </div>

      {(!detailA || !detailB) && (
        <div className="bg-card rounded-card shadow-card py-16 px-8 text-center text-ink-3 text-sm">
          选择两款产品后，这里会展示共有成分与各自独有成分
        </div>
      )}

      {detailA && detailB && comparison && (
        <>
          <div className="card">
            <h2 className="card-title">共有成分（{comparison.shared.length} 种）</h2>
            {comparison.shared.length === 0 ? (
              <div className="notice !mb-0">两款产品没有共有成分。</div>
            ) : (
              <>
                <div className="notice">
                  带 <span className="badge-ok mx-1">有证据</span> 标记的成分在证据库中有功效断言，点击查看证据链。
                </div>
                <div className="border border-line rounded-xl overflow-hidden">
                  {comparison.shared.map((i) => (
                    <IngredientRow key={i.ingredient_id} ing={i} showEvidence />
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="grid md:grid-cols-2 gap-5">
            {[
              ['A', detailA, comparison.onlyA],
              ['B', detailB, comparison.onlyB],
            ].map(([tag, detail, list]) => (
              <div key={tag} className="card !mb-0">
                <h2 className="card-title">仅产品 {tag} 独有（{list.length} 种）</h2>
                <div className="text-xs text-ink-3 mb-3 leading-snug">
                  <Link to={`/products/${detail.id}`} className="text-brand hover:underline">{detail.name}</Link>
                </div>
                {list.length === 0 ? (
                  <div className="text-sm text-ink-3">无独有成分。</div>
                ) : (
                  <div className="border border-line rounded-xl overflow-hidden max-h-[480px] overflow-y-auto">
                    {list.map((i) => <IngredientRow key={i.ingredient_id} ing={i} showEvidence />)}
                    </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
