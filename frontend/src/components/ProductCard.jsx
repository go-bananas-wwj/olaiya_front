import { Link } from 'react-router-dom'

// 产品卡片：列表页与对比页共用（名称/品牌/备案号/宣称数/成分数 + 有无宣称依据徽章）
export default function ProductCard({ p }) {
  return (
    <Link
      to={`/products/${p.id}`}
      className="block rounded-card p-5 bg-white/75 backdrop-blur-sm border border-[rgba(138,90,106,0.15)] shadow-card hover:ring-2 hover:ring-rosewood/40 transition-shadow"
    >
      <div className="font-semibold text-[15px] leading-snug text-pearl-ink">{p.name}</div>
      <div className="text-xs text-pearl-ink-3 mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
        <span>{p.brand}</span>
        {p.nmpa_id && <span className="break-all">备案号 {p.nmpa_id}</span>}
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        {p.claim_count > 0
          ? <span className="badge-ok">宣称依据 <span className="font-num">{p.claim_count}</span></span>
          : <span className="badge-muted">无宣称摘要</span>}
        <span className="badge-brand">成分 <span className="font-num">{p.ingredient_count}</span></span>
      </div>
    </Link>
  )
}
