import { Link } from 'react-router-dom'

// 产品卡片：列表页与对比页共用
export default function ProductCard({ p }) {
  return (
    <Link
      to={`/products/${p.id}`}
      className="block bg-card rounded-card shadow-card p-5 hover:ring-2 hover:ring-brand/40 transition-shadow"
    >
      <div className="font-semibold text-[15px] leading-snug">{p.name}</div>
      <div className="text-xs text-ink-3 mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
        <span>{p.brand}</span>
        {p.nmpa_id && <span className="break-all">备案号 {p.nmpa_id}</span>}
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        {p.claim_count > 0
          ? <span className="badge-ok">宣称依据 {p.claim_count}</span>
          : <span className="badge-muted">无宣称摘要</span>}
        <span className="badge-brand">成分 {p.ingredient_count}</span>
      </div>
    </Link>
  )
}
