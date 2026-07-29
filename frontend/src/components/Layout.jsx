import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/', label: '总览', end: true },
  { to: '/chat', label: '成分问答' },
  { to: '/roundtable', label: '圆桌核验' },
  { to: '/products', label: '产品库' },
  { to: '/ingredients', label: '成分库' },
  { to: '/compare', label: '产品对比' },
]

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-gradient-to-br from-brand-deep via-brand-dark to-brand text-white">
        <div className="max-w-6xl mx-auto px-5 pt-7 pb-5">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-4 justify-between">
            <h1 className="text-2xl tracking-wide flex items-center gap-3 font-bold">
              <span className="w-9 h-9 rounded-[10px] bg-white/15 inline-flex items-center justify-center text-lg">真</span>
              成分真言
            </h1>
            <nav className="flex gap-1">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) =>
                    `px-4 py-1.5 rounded-full text-sm transition-colors ${
                      isActive ? 'bg-white/20 font-semibold' : 'text-white/75 hover:bg-white/10 hover:text-white'
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <p className="mt-3 text-[13px] text-[#cfc6f0] max-w-3xl">
            敢说真话的成分核验平台：每条功效断言都挂真实文献。
          </p>
          <div className="flex flex-wrap gap-2 mt-3.5 text-xs">
            <span className="bg-white/10 border border-white/20 px-3 py-1 rounded-full">
              数据链路：<b className="text-[#ffd98a] font-semibold">NMPA 备案公示</b> → 盖德镜像采集 → 本地证据库 → API → 本页面
            </span>
          </div>
        </div>
      </header>

      <main className="flex-1 w-full max-w-6xl mx-auto px-5 py-6">
        <Outlet />
      </main>

      <footer className="text-center text-xs text-ink-3 pb-8 px-5">
        成分真言 · 欧莱雅美妆科技黑客松 2026 · 数据来源于 NMPA 备案公示镜像，仅供研究演示
      </footer>
    </div>
  )
}
