import { Link } from 'react-router-dom'

// 匹配分角标（降级方案）：匹配分需详情/指纹/浓度三接口，列表页逐产品请求=N+1 拖慢列表。
// 改为纯 localStorage：已设肤质档案（yj_profile）时，访问过详情页的产品显示缓存分
// （详情页 MatchScore 算完写入 yj_match_{id}），未访问过的提示「匹配分详情页可见」。
function matchBadge(id) {
  try {
    if (!localStorage.getItem('yj_profile')) return null
    const cached = JSON.parse(localStorage.getItem(`yj_match_${id}`) || 'null')
    if (cached && typeof cached.score === 'number') {
      return <span className="pearl-badge-iris">匹配 <span className="font-num">{cached.score}</span></span>
    }
    return <span className="pearl-badge-muted">匹配分详情页可见</span>
  } catch { return null }
}

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
        {matchBadge(p.id)}
      </div>
    </Link>
  )
}
