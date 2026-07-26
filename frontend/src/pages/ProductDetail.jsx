import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from '../components/common'
import ClaimCard from '../components/ClaimCard'

export default function ProductDetail() {
  const { id } = useParams()
  const { data: p, loading, error } = useFetch(() => api.product(id), [id])

  if (loading) return <div className="card"><Loading /></div>
  if (error) return <div className="card"><LoadError error={error} /></div>

  // 备案人/备案日期/来源为后端结构化字段；note 仅含功效描述，提取功效词
  const effMatch = (p.note || '').match(/功效: ([^（；]*)/)
  const kv = [
    p.registrant && ['备案人', p.registrant],
    p.filing_date && ['备案日期', p.filing_date],
    effMatch && ['宣称功效', effMatch[1]],
    p.price_current != null && ['参考价（人工采样）', `¥${p.price_current}`],
  ].filter(Boolean)

  return (
    <div>
      <Link to="/products" className="text-sm text-brand hover:underline">← 返回产品库</Link>

      <div className="card mt-3">
        <div className="text-xl md:text-2xl font-bold">{p.name}</div>
        <div className="text-[13px] text-ink-2 mt-2 flex flex-wrap gap-x-4 gap-y-1">
          <span>品牌：<b>{p.brand}</b></span>
          {p.nmpa_id && <span>备案号：<b>{p.nmpa_id}</b></span>}
          {p.category && <span>类别：{p.category}</span>}
        </div>
        {kv.length > 0 && (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 mt-4">
            {kv.map(([k, v]) => (
              <div key={k} className="bg-bg rounded-[10px] px-3.5 py-2.5">
                <div className="kv-label">{k}</div>
                <div className="kv-value">{v}</div>
              </div>
            ))}
          </div>
        )}
        {p.source_url && (
          <div className="text-xs text-ink-3 mt-4 break-all">
            备案数据来源：
            <a href={p.source_url} target="_blank" rel="noreferrer" className="text-brand hover:underline">
              {p.source_url}
            </a>
            （NMPA 公示镜像）
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">功效宣称依据（{p.claims.length} 条）</h2>
        {p.claims.length === 0 ? (
          <div className="notice !mb-0">
            该产品备案页未公示《功效宣称依据摘要》（可能属 2021 年前备案或清洁/物理遮盖等法定免公布情形）
            ——「查不到摘要」本身也是核验信号。
          </div>
        ) : (
          p.claims.map((c, i) => <ClaimCard key={i} claim={c} nmpaId={p.nmpa_id} />)
        )}
      </div>

      <div className="card">
        <h2 className="card-title">产品成分表（{p.ingredients.length} 种）</h2>
        <div className="notice">
          带 <span className="badge-ok mx-1">有文献证据</span> 徽章的成分在证据库中有功效断言与文献支撑，点击查看证据链。
          「安全风险/活性/使用目的」为镜像站标注列。
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="th">成分名称</th>
                <th className="th">安全风险</th>
                <th className="th">活性成分</th>
                <th className="th">使用目的</th>
                <th className="th">证据</th>
              </tr>
            </thead>
            <tbody>
              {p.ingredients.map((ing) => (
                <tr key={ing.ingredient_id} className={ing.has_evidence ? 'bg-ok-soft/40 hover:bg-ok-soft/70' : 'hover:bg-bg'}>
                  <td className="td">
                    {ing.has_evidence ? (
                      <Link to={`/ingredients/${ing.ingredient_id}`} className="text-brand font-medium hover:underline">
                        {ing.cn_name || ing.inci_name}
                      </Link>
                    ) : (
                      ing.cn_name || ing.inci_name
                    )}
                    {ing.inci_name && ing.cn_name && (
                      <div className="text-xs text-ink-3">{ing.inci_name}</div>
                    )}
                  </td>
                  <td className="td tabular-nums">{ing.safety_risk ?? '—'}</td>
                  <td className="td">
                    {ing.is_active
                      ? <span className="text-ok font-semibold">活性</span>
                      : <span className="text-ink-3">—</span>}
                  </td>
                  <td className="td">{ing.purpose ?? '—'}</td>
                  <td className="td">
                    {ing.has_evidence
                      ? <Link to={`/ingredients/${ing.ingredient_id}`} className="badge-ok hover:ring-1 hover:ring-ok">有文献证据 →</Link>
                      : <span className="text-ink-3 text-xs">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
