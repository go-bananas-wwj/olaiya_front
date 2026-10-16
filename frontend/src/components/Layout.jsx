import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

const NAV = [
  { to: '/products', label: '产品库' },
  { to: '/ingredients', label: '成分库' },
  { to: '/rankings', label: '排行榜' },
  { to: '/compare', label: '对比' },
  { to: '/decode', label: '解码' },
  { to: '/roundtable', label: '圆桌核验' },
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
            <NavLink to="/" className="font-sans text-[22px] font-semibold tracking-[0.14em] text-pearl-ink">颜鉴</NavLink>
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
        <div>数据来源包括品牌公开资料、INCIDecoder、备案信息镜像与文献等；具体来源见详情</div>
        <div>颜鉴 · 欧莱雅美妆科技黑客松 2026 · 浓度为估计值，相似不代表功效等同</div>
      </footer>
    </div>
  )
}
