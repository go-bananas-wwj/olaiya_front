import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch, Loading, LoadError } from '../components/common'

const STAT_DEFS = [
  ['products', '备案产品', '款'],
  ['brands', '覆盖品牌', '个'],
  ['ingredients', '收录成分', '种'],
  ['ingredients_with_evidence', '有文献证据的成分', '种'],
  ['product_ingredients', '产品-成分关联', '条'],
  ['claims', '功效宣称依据', '条'],
  ['assertions', '功效断言', '条'],
  ['evidence', '证据文献', '篇'],
]

const CHAIN = [
  ['NMPA 备案公示', '国家药监局化妆品备案与功效宣称依据摘要，法定公示口径'],
  ['盖德镜像采集', '对公示数据镜像站进行结构化采集，保留备案号与宣称明细'],
  ['本地证据库', '成分功效断言逐条挂接 PubMed 文献等真实证据'],
  ['API 开放服务', 'FastAPI 统一输出统计、产品、成分与证据链数据'],
]

export default function Home() {
  const { data: stats, loading, error } = useFetch(api.stats, [])

  return (
    <div>
      <div className="card bg-gradient-to-br from-brand-deep via-brand-dark to-brand !text-white border-0">
        <h2 className="text-xl md:text-2xl font-bold leading-snug">
          敢说真话的成分核验平台
        </h2>
        <p className="mt-2 text-sm text-[#cfc6f0] max-w-3xl">
          每条功效断言都挂真实文献：把企业向 NMPA 公示的「功效宣称依据」与独立文献证据摆在一起，
          宣称有没有支撑，一眼可见。
        </p>
        <div className="flex flex-wrap gap-3 mt-5">
          <Link to="/products" className="bg-white text-brand-dark font-semibold text-sm px-5 py-2 rounded-full hover:bg-brand-soft transition-colors">
            浏览产品库 →
          </Link>
          <Link to="/ingredients" className="bg-white/15 border border-white/25 text-white text-sm px-5 py-2 rounded-full hover:bg-white/25 transition-colors">
            查证成分证据 →
          </Link>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">数据规模</h2>
        {loading && <Loading />}
        {error && <LoadError error={error} />}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {STAT_DEFS.map(([key, label, unit]) => (
              <div key={key} className="bg-bg rounded-xl px-4 py-3.5">
                <div className="text-2xl font-bold text-brand tabular-nums">{stats[key]}</div>
                <div className="text-xs text-ink-3 mt-1">{label}（{unit}）</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">数据链路</h2>
        <div className="grid md:grid-cols-4 gap-3">
          {CHAIN.map(([title, desc], i) => (
            <div key={title} className="relative border border-line rounded-xl p-4">
              <div className="badge-brand mb-2">环节 {i + 1}</div>
              <div className="font-semibold text-sm">{title}</div>
              <div className="text-xs text-ink-2 mt-1.5 leading-relaxed">{desc}</div>
              {i < CHAIN.length - 1 && (
                <div className="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 text-brand font-bold z-10">→</div>
              )}
            </div>
          ))}
        </div>
        <div className="notice !mb-0 mt-4">
          「查不到宣称摘要」本身也是核验信号：2021 年前备案或法定免公布情形下，产品可能没有公示《功效宣称依据摘要》。
        </div>
      </div>
    </div>
  )
}
