import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from '../components/common'
import EfficacyBoard from '../components/EfficacyBoard'

const EFFICACY_CAPS = ['美白', '抗老', '保湿', '祛痘']

const ENTRY_CARDS = [
  {
    to: '/products',
    title: '查产品',
    desc: '宣称对证据，一眼看穿',
    icon: '查',
  },
  {
    to: '/decode',
    title: '解码成分表',
    desc: '粘贴成分表，逐成分出证据报告',
    icon: '解',
  },
  {
    to: '/chat',
    title: 'AI 问答',
    desc: '逐句挂文献的回答',
    icon: '问',
  },
]

export default function Home() {
  const navigate = useNavigate()
  const [kw, setKw] = useState('')
  const { data: stats } = useFetch(api.stats, [])

  return (
    <div className="pearl-page">
      {/* 首屏：大标题 + slogan + 大搜索框 + 功效胶囊 */}
      <section className="text-center pt-8 pb-10 md:pt-12">
        <h1 className="font-display text-5xl md:text-6xl tracking-[0.3em] grad-text">颜鉴</h1>
        <p className="mt-3 text-pearl-ink-2 text-sm md:text-base tracking-wide">
          每条功效断言，都挂真实文献
        </p>
        <div className="mt-7 mx-auto max-w-xl">
          <input
            className="w-full rounded-full border-2 border-rosewood/60 bg-white/85 px-6 py-3.5 text-sm outline-none shadow-[0_14px_30px_-14px_rgba(61,47,42,0.4)] focus:border-rosewood transition-colors"
            placeholder="输入产品名 / 成分名 / 备案号，如「OLAY 小白瓶」「烟酰胺」…"
            value={kw}
            onChange={(e) => setKw(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing && kw.trim()) {
                navigate(`/search?q=${encodeURIComponent(kw.trim())}`)
              }
            }}
          />
        </div>
        <div className="mt-5 flex flex-wrap justify-center gap-2.5">
          {EFFICACY_CAPS.map((cap) => (
            <Link
              key={cap}
              to={`/products?efficacy=${encodeURIComponent(cap)}`}
              className="fairy-chip !text-sm !px-4 !py-1.5 hover:bg-rosewood/20 transition-colors"
            >
              {cap}
            </Link>
          ))}
        </div>
      </section>

      {/* 数据规模一行（实时取自 /api/stats） */}
      {stats && (
        <p className="text-center text-sm text-pearl-ink-2 mb-8">
          <span className="font-num font-bold text-pearl-ink">{stats.products}</span> 款产品 ·{' '}
          <span className="font-num font-bold text-pearl-ink">{stats.ingredients}</span> 个成分 ·{' '}
          <span className="font-num font-bold text-pearl-ink">{stats.evidence}</span> 条真实文献证据
        </p>
      )}

      {/* 功效证据榜 Top5 */}
      <div className="glass-card">
        <div className="flex items-center justify-between mb-1">
          <h2 className="pearl-title !mb-0">功效证据榜</h2>
          <Link to="/rankings" className="text-xs text-rosewood hover:underline flex-shrink-0">
            完整榜单 →
          </Link>
        </div>
        <div className="mt-4">
          <EfficacyBoard limit={5} />
        </div>
      </div>

      {/* 三入口卡 */}
      <div className="grid md:grid-cols-3 gap-4">
        {ENTRY_CARDS.map((c) => (
          <Link key={c.to} to={c.to} className="glass-card !mb-0 block hover:-translate-y-0.5 transition-transform">
            <span className="w-10 h-10 rounded-full bg-gradient-to-br from-rosewood to-iris text-white inline-flex items-center justify-center font-display text-lg border-2 border-white/90 shadow-[0_2px_6px_rgba(61,47,42,0.25)] mb-3">
              {c.icon}
            </span>
            <div className="font-display text-base tracking-wider">{c.title}</div>
            <div className="text-xs text-pearl-ink-2 mt-1.5">{c.desc}</div>
          </Link>
        ))}
      </div>
    </div>
  )
}
