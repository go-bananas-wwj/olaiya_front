import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

const EXAMPLES = [
  '烟酰胺真的能美白吗？',
  '视黄醇抗皱有证据吗？',
  'VC 真的能美白吗？',
]

const WELCOME = '你好，我是成分真言问答助手：只根据证据库回答，每条结论挂真实文献。点击下面的示例问题，或直接输入你关心的成分功效问题。'

const CHANNEL_BADGE = {
  local: { label: '910B 本地', cls: 'badge-ok' },
  cloud: { label: '云端 API', cls: 'badge-brand' },
}

const CITE_RE = /\[(\d{1,3})\]/
const CITE_SPLIT_RE = /(\[\d{1,3}\])/g
const URL_RE = /https?:\/\/[^\s，,）)]+/

function channelBadge(channel) {
  const c = CHANNEL_BADGE[channel] || { label: channel || '未知通道', cls: 'badge-muted' }
  return <span className={c.cls}>{c.label}</span>
}

// 答案文本中的 [n] 引用编号渲染为可点击徽章；包外编号（幻觉引用）标红
function AnswerText({ text, hallucinated, onCite }) {
  const parts = text.split(CITE_SPLIT_RE)
  return (
    <div className="whitespace-pre-wrap text-sm leading-relaxed">
      {parts.map((p, i) => {
        const m = p.match(new RegExp(`^${CITE_RE.source}$`))
        if (!m) return <span key={i}>{p}</span>
        const n = Number(m[1])
        const bad = hallucinated.includes(n)
        return (
          <button
            key={i}
            type="button"
            onClick={() => onCite(n)}
            title={bad ? `引用 [${n}] 不在证据库中` : `查看证据 [${n}]`}
            className={`inline-flex items-center mx-0.5 px-1.5 rounded-md text-xs font-semibold align-baseline transition-colors ${
              bad
                ? 'bg-[#fde8e8] text-[#c81e1e] hover:bg-[#f9d5d5]'
                : 'bg-brand-soft text-brand hover:bg-brand hover:text-white'
            }`}
          >
            [{n}]
          </button>
        )
      })}
    </div>
  )
}

// 证据卡：编号 + 类型标签 + 文本（PMID/来源链接单独渲染为可点链接）
function EvidenceCard({ msgId, item, active, expanded, onToggle }) {
  const url = item.text.match(URL_RE)?.[0] || null
  const pmid = url?.match(/pubmed\.ncbi\.nlm\.nih\.gov\/(\d+)/)?.[1] || null
  // 移除 URL 后清理留下的连续/结尾逗号
  const displayText = url
    ? item.text.replace(URL_RE, '').replace(/([，,]\s*){2,}/g, '，').replace(/[，,]\s*$/, '')
    : item.text
  return (
    <div
      id={`ev-${msgId}-${item.id}`}
      onClick={onToggle}
      className={`w-full text-left border rounded-[10px] px-3.5 py-2.5 cursor-pointer transition-all ${
        active
          ? 'border-brand bg-brand-soft/60 ring-2 ring-brand/40'
          : 'border-line bg-bg hover:border-brand/50'
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="inline-flex items-center px-1.5 rounded-md bg-brand-soft text-brand text-xs font-bold">
          [{item.id}]
        </span>
        {item.kind === 'assertion' ? (
          <span className="badge-brand">功效断言</span>
        ) : (
          <span className="badge-ok">NMPA 宣称</span>
        )}
        {pmid ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="ml-auto text-xs text-brand hover:underline flex-shrink-0"
          >
            PMID {pmid} ↗
          </a>
        ) : url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="ml-auto text-xs text-brand hover:underline flex-shrink-0"
          >
            来源链接 ↗
          </a>
        ) : null}
      </div>
      <div className={`text-xs leading-relaxed text-ink-2 ${expanded ? '' : 'line-clamp-2'}`}>
        {displayText}
      </div>
    </div>
  )
}

// AI 回答卡：通道徽章 + 幻觉引用警示 + 回答文本 + 证据包面板
function AnswerCard({ msg }) {
  const { answer, evidence_pack: pack, hallucinated_citations: hallucinated, channel } = msg.data
  const [activeEv, setActiveEv] = useState(null) // 当前高亮/展开的证据编号

  const handleCite = (n) => {
    if (!pack.some((it) => it.id === n)) return // 包外编号无卡可跳
    setActiveEv(n)
    requestAnimationFrame(() => {
      document.getElementById(`ev-${msg.id}-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }

  return (
    <div className="bg-card rounded-card shadow-card p-5 md:p-6 max-w-full">
      <div className="flex items-center justify-between gap-2 mb-3">
        <span className="text-xs font-semibold text-ink-3">真言助手</span>
        {channelBadge(channel)}
      </div>

      {hallucinated.length > 0 && (
        <div className="rounded-[10px] bg-[#fde8e8] text-[#c81e1e] px-4 py-2.5 text-xs leading-relaxed mb-3 font-medium">
          检测到 {hallucinated.map((n) => `[${n}]`).join('')} 号引用不在证据库中，请谨慎采信。
        </div>
      )}

      <AnswerText text={answer} hallucinated={hallucinated} onCite={handleCite} />

      {pack.length > 0 && (
        <div className="mt-4 pt-3 border-t border-line">
          <div className="text-xs font-semibold text-ink-3 mb-2">
            本条回答引用的证据（{pack.length} 条，点击回答中的 [n] 定位）
          </div>
          <div className="space-y-2">
            {pack.map((it) => (
              <EvidenceCard
                key={it.id}
                msgId={msg.id}
                item={it}
                active={activeEv === it.id}
                expanded={activeEv === it.id}
                onToggle={() => setActiveEv(activeEv === it.id ? null : it.id)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function TypingBubble() {
  return (
    <div className="bg-card rounded-card shadow-card px-5 py-4 flex items-center gap-2 text-ink-3">
      <span className="text-xs">正在检索证据并生成回答</span>
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

export default function Chat() {
  const [messages, setMessages] = useState([{ id: 0, role: 'assistant', welcome: true }])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const idRef = useRef(1)
  const endRef = useRef(null)

  const showExamples = messages.length === 1 && !sending

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  async function send(question) {
    const q = (question ?? input).trim()
    if (!q || sending) return
    setSending(true)
    setInput('')
    setMessages((ms) => [...ms, { id: idRef.current++, role: 'user', text: q }])
    try {
      const data = await api.chat(q)
      const aid = idRef.current++
      setMessages((ms) => [...ms, { id: aid, role: 'assistant', data }])
    } catch (e) {
      const text = e.status === 503 ? 'LLM 暂不可用，请稍后再试。' : `请求失败：${e.message}`
      const aid = idRef.current++
      setMessages((ms) => [...ms, { id: aid, role: 'assistant', error: text }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="space-y-4 mb-5">
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%] bg-brand text-white rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed shadow-card whitespace-pre-wrap">
                {m.text}
              </div>
            </div>
          ) : m.welcome ? (
            <div key={m.id} className="flex">
              <div className="max-w-[92%] bg-card rounded-card shadow-card p-5">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="w-6 h-6 rounded-lg bg-brand-soft text-brand inline-flex items-center justify-center text-xs font-bold">真</span>
                  <span className="text-xs font-semibold text-ink-3">真言助手</span>
                </div>
                <div className="text-sm leading-relaxed">{WELCOME}</div>
              </div>
            </div>
          ) : m.error ? (
            <div key={m.id} className="flex">
              <div className="max-w-[92%] rounded-card bg-[#fde8e8] text-[#c81e1e] px-5 py-3.5 text-sm">
                {m.error}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex">
              <div className="max-w-[92%] min-w-0">
                <AnswerCard msg={m} />
              </div>
            </div>
          ),
        )}

        {showExamples && (
          <div className="flex flex-wrap gap-2 pl-1">
            {EXAMPLES.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => send(q)}
                className="px-3.5 py-1.5 rounded-full border border-brand/40 text-brand text-xs hover:bg-brand-soft transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        )}

        {sending && (
          <div className="flex">
            <TypingBubble />
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="card !mb-0 sticky bottom-4 p-3.5 flex gap-2.5">
        <input
          className="input"
          placeholder="输入成分功效问题，回车发送…"
          value={input}
          disabled={sending}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) send()
          }}
        />
        <button
          type="button"
          onClick={() => send()}
          disabled={sending || !input.trim()}
          className="flex-shrink-0 px-5 py-2 rounded-[10px] bg-brand text-white text-sm font-medium hover:bg-brand-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
        >
          {sending ? (
            <>
              <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              发送中
            </>
          ) : (
            '发送'
          )}
        </button>
      </div>
    </div>
  )
}
