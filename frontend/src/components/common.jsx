import { useEffect, useState } from 'react'

// 通用数据加载 hook：返回 { data, loading, error }
export function useFetch(fn, deps) {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  useEffect(() => {
    let alive = true
    setState({ data: null, loading: true, error: null })
    fn()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((e) => alive && setState({ data: null, loading: false, error: e.message || '请求失败' }))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

export function Loading({ text = '加载中…' }) {
  return <div className="py-14 text-center text-ink-3 text-sm">{text}</div>
}

export function LoadError({ error }) {
  return (
    <div className="notice">
      数据加载失败（{error}）——请确认后端已启动：
      <code className="ml-1">PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --port 8000</code>
    </div>
  )
}

export function Empty({ text }) {
  return (
    <div className="bg-card rounded-card shadow-card py-16 px-8 text-center text-ink-3 text-sm">
      {text}
    </div>
  )
}
