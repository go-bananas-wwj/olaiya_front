import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

const NAV = [
  { to: '/products', label: '产品库' },
  { to: '/ingredients', label: '成分库' },
  { to: '/rankings', label: '排行榜' },
  { to: '/compare', label: '对比' },
  { to: '/decode', label: '解码' },
  { to: '/chat', label: 'AI 问答' },
]

export default function Layout() {
  const navigate = useNavigate()
  const [kw, setKw] = useState('')

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white/40 backdrop-blur-md border-b border-[rgba(138,90,106,0.15)]">
        <div className="max-w-6xl mx-auto px-5 pt-5 pb-4">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-3 justify-between">
            <h1 className="font-sans text-[22px] font-semibold tracking-[0.14em] text-pearl-ink">颜鉴</h1>
            <nav className="flex gap-1 flex-wrap font-sans font-medium">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) =>
                    `px-4 py-1.5 rounded-full text-sm tracking-wider transition-colors ${
                      isActive
                        ? 'bg-rosewood/15 text-rosewood font-semibold'
                        : 'text-pearl-ink hover:bg-white/50'
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </nav>
            <input
              className="input w-56 text-sm"
              placeholder="搜产品 / 成分 / 备案号…"
              value={kw}
              onChange={(e) => setKw(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.nativeEvent.isComposing && kw.trim()) {
                  navigate(`/search?q=${encodeURIComponent(kw.trim())}`)
                }
              }}
            />
          </div>
          <p className="mt-2.5 text-[13px] text-pearl-ink-2 max-w-3xl tracking-wide">
            看懂成分，也看见证据
          </p>
        </div>
      </header>

      <main className="flex-1 w-full max-w-6xl mx-auto px-5 py-6">
        <Outlet />
      </main>

      <footer className="text-center text-xs text-pearl-ink-3 pb-8 px-5 space-y-1 font-sans">
        <div>数据链路：NMPA 备案公示 → 盖德镜像采集 → 本地证据库 → API → 本页面</div>
        <div>颜鉴 · 欧莱雅美妆科技黑客松 2026 · 数据来源于 NMPA 备案公示镜像，仅供研究演示</div>
      </footer>
    </div>
  )
}
