import { useEffect, useRef, useState } from 'react'

const EXAMPLES = ['烟酰胺', '修丽可']

// 四角色视觉标识（与后端 roundtable.ROLES 的 key 对应；图标用单字徽章，与布局「真」字风格一致）
const ROLE_META = {
  ingredient_expert: {
    name: '成分专家', icon: '成',
    badge: 'bg-[#efeaff] text-[#6d4bd8]', dot: 'bg-[#6d4bd8]',
  },
  regulation_officer: {
    name: '法规合规官', icon: '规',
    badge: 'bg-[#e8f0fe] text-[#2563eb]', dot: 'bg-[#2563eb]',
  },
  evidence_verifier: {
    name: '文献核验官', icon: '文',
    badge: 'bg-[#e3f6ee] text-[#0e9f6e]', dot: 'bg-[#0e9f6e]',
  },
  dose_analyst: {
    name: '剂量推断师', icon: '剂',
    badge: 'bg-[#fdf3e0] text-[#b7791f]', dot: 'bg-[#b7791f]',
  },
}

// 工具名 → 中文标签（与后端 agent_tools 对应）
const TOOL_LABEL = {
  product_lookup: '产品库检索',
  similar_products: '相似产品比对',
  product_claims: 'NMPA 宣称摘要',
  ingredient_evidence: '文献证据检索',
  dose_check: '剂量达标判定',
}

// 五级判定配色：1红 / 2灰 / 3橙 / 4黄 / 5绿；2′「证据支持，剂量无法判定」按 4 级黄色
const VERDICT_THEMES = {
  red: { text: 'text-[#c81e1e]', soft: 'bg-[#fde8e8]', border: 'border-[#c81e1e]/25', chip: 'bg-[#c81e1e]' },
  gray: { text: 'text-[#6b7280]', soft: 'bg-[#f1f0f6]', border: 'border-[#6b7280]/25', chip: 'bg-[#6b7280]' },
  orange: { text: 'text-[#ea580c]', soft: 'bg-[#fff1e7]', border: 'border-[#ea580c]/25', chip: 'bg-[#ea580c]' },
  yellow: { text: 'text-[#a16207]', soft: 'bg-[#fef9c3]', border: 'border-[#a16207]/25', chip: 'bg-[#eab308]' },
  green: { text: 'text-[#0e9f6e]', soft: 'bg-[#e3f6ee]', border: 'border-[#0e9f6e]/25', chip: 'bg-[#0e9f6e]' },
}

function verdictTheme(level, label) {
  if (label === '证据支持，剂量无法判定') return VERDICT_THEMES.yellow // 2′ 同 4
  const map = { 1: 'red', 2: 'gray', 3: 'orange', 4: 'yellow', 5: 'green' }
  return VERDICT_THEMES[map[level]] || VERDICT_THEMES.gray
}

function roleMeta(role) {
  return ROLE_META[role] || { name: role, icon: '言', badge: 'badge-muted', dot: 'bg-ink-3' }
}

// SSE：POST + ReadableStream 逐事件解析（EventSource 不支持 POST，故用 fetch）
async function streamRoundtable(productName, signal, onEvent) {
  const res = await fetch('/api/roundtable', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_name: productName }),
    signal,
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const body = await res.json()
      if (body && body.detail) detail = body.detail
    } catch { /* 非 JSON 错误体 */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE 事件以空行分隔；逐块取出 data: 行
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') return 'done'
        try {
          onEvent(JSON.parse(payload))
        } catch { /* 忽略无法解析的事件，不中断流 */ }
      }
    }
  }
  return 'eof' // 连接结束但未收到 [DONE]
}

// 产品定位卡（start 事件）
function ProductCard({ product }) {
  return (
    <div className="bg-card rounded-card shadow-card p-5 md:p-6 animate-[fade-up_.3s_ease-out]">
      <div className="flex items-center gap-2 mb-2">
        <span className="badge-brand">圆桌对象</span>
        {product.matched_via === 'ingredient' && product.matched_ingredient && (
          <span className="badge-muted">经成分「{product.matched_ingredient.cn_name || product.matched_ingredient.inci_name}」命中</span>
        )}
      </div>
      <div className="text-lg font-bold leading-snug">{product.name}</div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-3">
        <span>品牌：<b className="text-ink-2 font-medium">{product.brand || '—'}</b></span>
        <span>备案号：<b className="text-ink-2 font-medium">{product.nmpa_id || '—'}</b></span>
        <span>成分 {product.ingredient_count} 项</span>
        <span>宣称 {product.claim_count} 条</span>
      </div>
    </div>
  )
}

// 工具调用紧凑行（灰字小字，可展开看 args 摘要）
function ToolCallRow({ item }) {
  const meta = roleMeta(item.role)
  const argsText = JSON.stringify(item.args, null, 2)
  return (
    <details className="group text-xs text-ink-3 animate-[fade-up_.2s_ease-out]">
      <summary className="flex items-center gap-2 cursor-pointer list-none select-none py-0.5">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${meta.dot}`} />
        <span className="font-medium">{meta.name}</span>
        <span className="text-ink-3/70">调用</span>
        <span className="text-ink-2 font-medium">{TOOL_LABEL[item.tool] || item.tool}</span>
        <span className="text-ink-3/50 group-open:rotate-90 transition-transform">▸</span>
      </summary>
      <pre className="mt-1 ml-3.5 px-3 py-2 rounded-lg bg-bg border border-line text-[11px] leading-relaxed overflow-x-auto whitespace-pre-wrap break-all">
        {argsText}
      </pre>
    </details>
  )
}

// 角色发言卡（等待态显示「打字中…」）
function SpeakCard({ item, pending }) {
  const meta = roleMeta(item.role)
  return (
    <div className="bg-card rounded-card shadow-card p-5 animate-[fade-up_.3s_ease-out]">
      <div className="flex items-center gap-2 mb-2.5">
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${meta.badge}`}>
          <span>{meta.icon}</span>
          {meta.name}
        </span>
        {pending ? (
          <span className="flex items-center gap-1.5 text-xs text-ink-3">
            打字中
            <span className="flex gap-0.5">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="w-1 h-1 rounded-full bg-ink-3 animate-bounce"
                  style={{ animationDelay: `${i * 0.15}s` }}
                />
              ))}
            </span>
          </span>
        ) : (
          <span className="text-xs text-ok">✓ 发言完毕</span>
        )}
      </div>
      {!pending && (
        <div className="text-sm leading-relaxed whitespace-pre-wrap">{item.content}</div>
      )}
    </div>
  )
}

// 裁决等待动画
function JudgingCard() {
  return (
    <div className="bg-card rounded-card shadow-card px-5 py-4 flex items-center gap-2.5 text-ink-3 animate-[fade-up_.3s_ease-out]">
      <span className="w-6 h-6 rounded-lg bg-brand-soft text-brand inline-flex items-center justify-center text-xs font-bold">裁</span>
      <span className="text-xs">裁决官综合四方发言与工具数据，五级判定中</span>
      <span className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-brand animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </span>
    </div>
  )
}

// 压轴裁决卡：级别大字 + 五级刻度 + 理由
function VerdictCard({ verdict }) {
  const theme = verdictTheme(verdict.level, verdict.label)
  const activeLevel = verdict.label === '证据支持，剂量无法判定' ? 4 : verdict.level
  return (
    <div className={`rounded-card border-2 ${theme.border} ${theme.soft} shadow-card p-6 md:p-7 animate-[fade-up_.4s_ease-out]`}>
      <div className="flex items-center gap-2 mb-3">
        <span className="w-6 h-6 rounded-lg bg-brand-soft text-brand inline-flex items-center justify-center text-xs font-bold">裁</span>
        <span className="text-xs font-semibold tracking-wide text-ink-3">圆桌裁决 · 五级判定</span>
        {verdict.level != null && (
          <span className={`ml-auto inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold text-white ${theme.chip}`}>
            Lv.{verdict.level}
          </span>
        )}
      </div>
      <div className={`text-2xl md:text-3xl font-extrabold leading-snug ${theme.text}`}>
        {verdict.label}
      </div>
      {/* 五级刻度（1红→5绿），高亮命中级 */}
      <div className="flex gap-1.5 mt-4">
        {[1, 2, 3, 4, 5].map((lv) => {
          const t = VERDICT_THEMES[{ 1: 'red', 2: 'gray', 3: 'orange', 4: 'yellow', 5: 'green' }[lv]]
          const active = activeLevel === lv
          return (
            <div key={lv} className="flex-1">
              <div className={`h-1.5 rounded-full ${active ? t.chip : 'bg-ink-3/15'}`} />
              <div className={`mt-1 text-center text-[10px] ${active ? `${t.text} font-bold` : 'text-ink-3/60'}`}>
                {lv}
              </div>
            </div>
          )
        })}
      </div>
      {verdict.reason && (
        <div className="mt-4 text-sm leading-relaxed text-ink-2">{verdict.reason}</div>
      )}
      <div className="mt-3 text-[11px] text-ink-3/80">
        判定综合四位角色的工具数据与发言；剂量相关表述为估计值。
      </div>
    </div>
  )
}

export default function Roundtable() {
  const [phase, setPhase] = useState('idle') // idle | streaming | done | error
  const [input, setInput] = useState('')
  const [product, setProduct] = useState(null)
  const [timeline, setTimeline] = useState([]) // tool_call / speak 按到达顺序
  const [verdict, setVerdict] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)
  const idRef = useRef(0)
  const abortRef = useRef(null)
  const endRef = useRef(null)

  const streaming = phase === 'streaming'
  const speakCount = timeline.filter((t) => t.kind === 'speak').length
  // 等待发言的角色：最近一个 tool_call 所属、且尚未发言
  const pendingRole = streaming
    ? [...timeline].reverse().find((t) => t.kind === 'tool' &&
        !timeline.some((s) => s.kind === 'speak' && s.role === t.role))?.role
    : null
  const judging = streaming && !pendingRole && speakCount >= 4 && !verdict

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [timeline, verdict, errorMsg, pendingRole, judging])

  useEffect(() => () => abortRef.current?.abort(), [])

  function handleEvent(ev) {
    if (ev.event === 'start') {
      setProduct(ev.product?.products?.[0] || null)
    } else if (ev.event === 'tool_call') {
      setTimeline((ts) => [...ts, { kind: 'tool', id: idRef.current++, role: ev.role, tool: ev.tool, args: ev.args }])
    } else if (ev.event === 'speak') {
      setTimeline((ts) => [...ts, { kind: 'speak', id: idRef.current++, role: ev.role, content: ev.content }])
    } else if (ev.event === 'verdict') {
      setVerdict(ev)
    } else if (ev.event === 'error') {
      setErrorMsg(ev.message || '圆桌流程出错')
      setPhase('error')
    }
  }

  async function start(name) {
    const q = (name ?? input).trim()
    if (!q || streaming) return
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setPhase('streaming')
    setInput('')
    setProduct(null)
    setTimeline([])
    setVerdict(null)
    setErrorMsg(null)
    try {
      const result = await streamRoundtable(q, ctrl.signal, handleEvent)
      setPhase((p) => {
        if (p === 'error') return p // 流内 error 事件优先
        return result === 'done' ? 'done' : p
      })
      if (result === 'eof') {
        setPhase('error')
        setErrorMsg('连接中断：未收到结束标记，请重试。')
      }
    } catch (e) {
      if (e.name === 'AbortError') return
      setPhase('error')
      setErrorMsg(e.status === 503 ? 'LLM 暂不可用，请稍后再试。' : `连接失败：${e.message}`)
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="pearl-badge-muted mb-3">实验功能 · 二期上线</div>
      {/* 输入区 */}
      <div className="card">
        <div className="card-title">圆桌核验</div>
        <p className="text-xs text-ink-3 leading-relaxed mb-4 -mt-2">
          四位 AI 角色各持独占信息源（产品库 / NMPA 宣称 / 文献证据 / 浓度引擎）分别核验，
          裁决官综合给出五级判定。输入产品名（或成分名）开始一场圆桌。
        </p>
        <div className="flex gap-2.5">
          <input
            className="input"
            placeholder="输入产品名，如「修丽可」，回车开始…"
            value={input}
            disabled={streaming}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) start()
            }}
          />
          <button
            type="button"
            onClick={() => start()}
            disabled={streaming || !input.trim()}
            className="flex-shrink-0 px-5 py-2 rounded-[10px] bg-brand text-white text-sm font-medium hover:bg-brand-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
          >
            {streaming ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                讨论中
              </>
            ) : (
              '开始圆桌'
            )}
          </button>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          <span className="text-xs text-ink-3 py-1">示例：</span>
          {EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              disabled={streaming}
              onClick={() => start(q)}
              className="px-3.5 py-1.5 rounded-full border border-brand/40 text-brand text-xs hover:bg-brand-soft transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* 讨论过程区 */}
      <div className="space-y-4">
        {product && <ProductCard product={product} />}

        {timeline.map((item) =>
          item.kind === 'tool' ? (
            <ToolCallRow key={item.id} item={item} />
          ) : (
            <SpeakCard key={item.id} item={item} pending={false} />
          ),
        )}

        {pendingRole && <SpeakCard item={{ role: pendingRole }} pending />}

        {judging && <JudgingCard />}

        {verdict && <VerdictCard verdict={verdict} />}

        {errorMsg && (
          <div className="rounded-card bg-[#fde8e8] text-[#c81e1e] px-5 py-3.5 text-sm animate-[fade-up_.3s_ease-out]">
            {errorMsg}
          </div>
        )}

        {phase === 'done' && (
          <div className="text-center text-xs text-ink-3 pt-1">圆桌结束，可输入下一个产品名再开一场。</div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}
