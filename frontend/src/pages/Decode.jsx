import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

// 逐成分查询并发上限（简单工作队列，防一次性打爆后端）
const CONCURRENCY = 4
const SPLIT_RE = /[、，,；;\n\r]+/
// 与后端 _FOLD_RE 一致的折叠比对：忽略大小写/空格/连字符
const fold = (s) => (s || '').replace(/[\s-]+/g, '').toLowerCase()

// 粘贴文本 → 成分词列表：按顿号/逗号/分号/换行分割，去空白去重（折叠形去重）
// 数字间的半角逗号不算分隔符（「1,2-戊二醇」「1,3-丙二醇」这类 IECIC 名内含逗号）
function parseWords(text) {
  const seen = new Set()
  const words = []
  const safe = text.replace(/(\d),(\d)/g, '$1\u0000$2')
  for (const raw of safe.split(SPLIT_RE)) {
    const w = raw.replace(/(\d)\u0000(\d)/g, '$1,$2').trim()
    if (!w) continue
    const key = fold(w)
    if (seen.has(key)) continue
    seen.add(key)
    words.push(w)
  }
  return words
}

// 单词匹配：名称精确相等优先，其次折叠相等，否则取第一条标「存疑匹配」
async function matchWord(word) {
  const res = await api.ingredients({ q: word, limit: 3 })
  const items = res.items ?? res
  if (!items.length) return { word, status: 'miss' }
  const exact = items.find(
    (i) => i.cn_name === word || (i.inci_name || '').toLowerCase() === word.toLowerCase(),
  )
  if (exact) return { word, status: 'hit', item: exact }
  const folded = items.find((i) => fold(i.cn_name) === fold(word) || fold(i.inci_name) === fold(word))
  if (folded) return { word, status: 'hit', item: folded }
  return { word, status: 'doubt', item: items[0], candidates: items }
}

// 并发上限 CONCURRENCY 的工作队列：worker 各取下标直到取完，无递归无死锁
async function runQueue(words, onOne) {
  let next = 0
  async function worker() {
    while (next < words.length) {
      const i = next
      next += 1
      let row
      try {
        row = await matchWord(words[i])
      } catch {
        row = { word: words[i], status: 'error' }
      }
      onOne(i, row)
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, words.length) }, () => worker()))
}

function HitRow({ row }) {
  const it = row.item
  const doubt = row.status === 'doubt'
  return (
    <div className="fairy-panel px-4 py-3 mb-2">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to={`/ingredients/${it.id}`}
          className="font-medium text-pearl-ink hover:text-rosewood transition-colors"
        >
          {it.cn_name || it.inci_name}
        </Link>
        {it.inci_name && <span className="text-xs text-pearl-ink-3">{it.inci_name}</span>}
        {doubt ? (
          <span className="pearl-badge-warn">存疑匹配</span>
        ) : (
          <span className="pearl-badge-ok">已命中</span>
        )}
        <span className={it.assertion_count > 0 ? 'pearl-badge-iris' : 'pearl-badge-muted'}>
          {it.assertion_count > 0 ? `${it.assertion_count} 条断言` : '暂无断言'}
        </span>
        {doubt && <span className="text-xs text-pearl-ink-3">输入「{row.word}」未精确命中</span>}
      </div>
      {doubt && row.candidates && (
        <div className="mt-1.5 text-xs text-pearl-ink-2">
          候选：
          {row.candidates.map((c, idx) => (
            <span key={c.id}>
              {idx > 0 && ' / '}
              <Link to={`/ingredients/${c.id}`} className="text-iris hover:underline">
                {c.cn_name || c.inci_name}
              </Link>
            </span>
          ))}
          ，请人工核对
        </div>
      )}
    </div>
  )
}

export default function Decode() {
  const [text, setText] = useState('')
  const [rows, setRows] = useState(null) // 与词表等长；null=未解析，status=pending 为解析中
  const [running, setRunning] = useState(false)
  const busyRef = useRef(false) // in-flight 防护：快速连点不重复发请求
  const runSeq = useRef(0) // 过期响应丢弃

  const onDecode = async () => {
    if (busyRef.current) return
    const words = parseWords(text)
    const my = ++runSeq.current
    if (!words.length) {
      setRows([])
      return
    }
    busyRef.current = true
    setRunning(true)
    setRows(words.map((w) => ({ word: w, status: 'pending' })))
    await runQueue(words, (i, row) => {
      if (my !== runSeq.current) return
      setRows((prev) => {
        if (!prev) return prev
        const nextRows = prev.slice()
        nextRows[i] = row
        return nextRows
      })
    })
    if (my === runSeq.current) {
      busyRef.current = false
      setRunning(false)
    }
  }

  const done = rows ? rows.filter((r) => r.status !== 'pending') : []
  const hits = done.filter((r) => r.status === 'hit' || r.status === 'doubt')
  const doubts = done.filter((r) => r.status === 'doubt')
  const misses = done.filter((r) => r.status === 'miss')
  const errors = done.filter((r) => r.status === 'error')

  return (
    <div className="pearl-page">
      <div className="glass-card relative">
        <div className="pearl-title">解码成分表</div>
        <p className="text-sm text-pearl-ink-2 mb-3">
          粘贴产品包装上的全成分表，逐个核对库中证据。中文名 / INCI 均可，顿号、逗号、分号或换行分隔。
        </p>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          placeholder="例：水、烟酰胺、聚甲基倍半硅氧烷、聚二甲基硅氧烷、甘油、丁二醇……"
          className="w-full px-4 py-3 rounded-[14px] text-sm bg-white/60 text-pearl-ink border-[1.5px] border-rosewood/25 outline-none focus:border-rosewood/60 transition-colors resize-y"
        />
        <div className="mt-4 flex items-center gap-3">
          <button type="button" onClick={onDecode} disabled={running} className="btn-fairy disabled:opacity-50 disabled:pointer-events-none">
            {running ? `解析中 ${done.length}/${rows.length}` : '解析'}
          </button>
          {rows && !running && (
            <button
              type="button"
              onClick={() => { setRows(null); setText('') }}
              className="btn-fairy-ghost"
            >
              清空
            </button>
          )}
        </div>
      </div>

      {rows && rows.length === 0 && (
        <div className="glass-card relative text-sm text-pearl-ink-2">没有可解析的成分词，请粘贴成分表后再点「解析」。</div>
      )}

      {rows && rows.length > 0 && (
        <div className="glass-card relative">
          <div className="pearl-title">证据报告</div>
          <p className="text-sm text-pearl-ink-2 mb-3">
            共 <span className="font-num font-semibold text-pearl-ink">{rows.length}</span> 个成分，
            命中 <span className="font-num font-semibold text-pearl-ink">{hits.length}</span> 个
            {doubts.length > 0 && <>（含存疑 <span className="font-num">{doubts.length}</span> 个）</>}，
            未命中 <span className="font-num font-semibold text-pearl-ink">{misses.length}</span> 个
            {errors.length > 0 && <>，查询失败 <span className="font-num">{errors.length}</span> 个</>}
            {running && <>（解析中…）</>}
          </p>
          <div className="pearl-notice">匹配按 IECIC 中文名 / INCI 折叠比对，存疑项请人工核对。</div>

          {hits.length > 0 && (
            <>
              <div className="text-sm font-medium text-pearl-ink mt-2 mb-2">已命中</div>
              {hits.map((r) => <HitRow key={r.word} row={r} />)}
            </>
          )}

          {misses.length > 0 && (
            <>
              <div className="text-sm font-medium text-pearl-ink mt-4 mb-2">未命中</div>
              {misses.map((r) => (
                <div key={r.word} className="fairy-panel-dim px-4 py-3 mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-sm text-pearl-ink">{r.word}</span>
                  <span className="pearl-badge-muted">库中无此成分</span>
                </div>
              ))}
            </>
          )}

          {errors.length > 0 && (
            <>
              <div className="text-sm font-medium text-pearl-ink mt-4 mb-2">查询失败</div>
              {errors.map((r) => (
                <div key={r.word} className="fairy-panel-dim px-4 py-3 mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-sm text-pearl-ink">{r.word}</span>
                  <span className="pearl-badge-bad">查询失败，请重新解析</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}
