import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from '../components/common'
import HomeEfficacyBoards from '../components/HomeEfficacyBoards'

const SEARCH_HINTS = [
  '搜索产品，例如：欧莱雅小白瓶',
  '搜索成分，例如：烟酰胺',
  '搜索备案号，例如：国妆特字……',
]

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
  const [hintIndex, setHintIndex] = useState(0)
  const { data: stats } = useFetch(api.stats, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setHintIndex((current) => (current + 1) % SEARCH_HINTS.length)
    }, 3200)
    return () => window.clearInterval(timer)
  }, [])

  function submitSearch(event) {
    event.preventDefault()
    if (kw.trim()) navigate(`/search?q=${encodeURIComponent(kw.trim())}`)
  }

  return (
    <div className="home-page">
      <section className="home-hero">
        <p className="home-kicker">成分与证据核验</p>
        <h1 className="home-wordmark">颜鉴</h1>
        <p className="home-slogan">每条功效断言，都有迹可循</p>
        <form className="home-search" onSubmit={submitSearch}>
          <label className="sr-only" htmlFor="home-search-input">搜索产品、成分或备案号</label>
          <input
            id="home-search-input"
            className="home-search-input"
            placeholder={SEARCH_HINTS[hintIndex]}
            value={kw}
            onChange={(e) => setKw(e.target.value)}
          />
          <button type="submit" className="home-search-button">搜索</button>
        </form>
      </section>

      {stats && (
        <p className="home-stats">
          <span>{stats.products}</span> 款产品 · <span>{stats.ingredients}</span> 个成分 · <span>{stats.evidence}</span> 条证据来源
        </p>
      )}

      <HomeEfficacyBoards />

      <div className="home-entry-links" aria-label="快捷入口">
        {ENTRY_CARDS.map((c) => (
          <Link key={c.to} to={c.to} className="home-entry-link">
            <span className="home-entry-icon">{c.icon}</span>
            <span>
              <span className="block text-sm font-medium">{c.title}</span>
              <span className="block text-xs text-pearl-ink-2 mt-0.5">{c.desc}</span>
            </span>
            <span aria-hidden="true" className="text-pearl-ink-3">›</span>
          </Link>
        ))}
      </div>
    </div>
  )
}
