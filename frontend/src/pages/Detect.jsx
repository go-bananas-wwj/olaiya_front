import { useEffect, useState } from 'react'
import { api } from '../api'

const VERDICT = {
  ai: { label: '疑似 AI 生成', cls: 'badge-danger', bar: 'bg-[#c81e1e]' },
  real: { label: '疑似真实照片', cls: 'badge-ok', bar: 'bg-ok' },
  uncertain: { label: '不确定', cls: 'badge-warn', bar: 'bg-warn' },
}

export default function Detect() {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    if (!file) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  function pick(e) {
    setFile(e.target.files?.[0] || null)
    setResult(null)
    setError(null)
  }

  async function submit() {
    if (!file || sending) return
    setSending(true)
    setError(null)
    setResult(null)
    try {
      setResult(await api.detectImage(file))
    } catch (e) {
      setError(e.status === 503 ? '检测服务未启动（视觉 sidecar 不可达），请稍后再试。' : `检测失败：${e.message}`)
    } finally {
      setSending(false)
    }
  }

  const v = result ? VERDICT[result.verdict] || VERDICT.uncertain : null

  return (
    <div className="max-w-2xl mx-auto">
      <div className="pearl-badge-muted mb-3">实验功能 · 二期上线</div>
      <div className="card">
        <div className="card-title">图片鉴伪（AI 生图检测）</div>
        <p className="text-xs text-ink-3 leading-relaxed mb-4">
          上传一张产品图/素材图，由 DINOv2 视觉模型估计其「AI 生成」概率。
          面向赛题「多模态」演示：识别品牌素材是否为 AI 生成图。
        </p>
        <div className="flex gap-2.5 items-center">
          <input type="file" accept="image/*" onChange={pick} className="input" />
          <button
            type="button"
            onClick={submit}
            disabled={!file || sending}
            className="flex-shrink-0 px-5 py-2 rounded-[10px] bg-brand text-white text-sm font-medium hover:bg-brand-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
          >
            {sending ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                检测中
              </>
            ) : (
              '开始检测'
            )}
          </button>
        </div>

        {preview && (
          <div className="mt-4">
            <img src={preview} alt="待检测图片预览" className="max-h-64 rounded-[10px] border border-line" />
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-[10px] bg-[#fde8e8] text-[#c81e1e] px-4 py-2.5 text-sm">{error}</div>
        )}

        {result && (
          <div className="mt-4 border border-line rounded-[10px] p-4">
            <div className="flex items-center gap-3 mb-2.5">
              <span className={v.cls}>{v.label}</span>
              <span className="text-sm text-ink-2">
                AI 生成概率（估计值）：<b>{(result.score * 100).toFixed(1)}%</b>
              </span>
            </div>
            <div className="h-2 rounded-full bg-[#f1f0f6] overflow-hidden">
              <div className={`h-full ${v.bar}`} style={{ width: `${Math.round(result.score * 100)}%` }} />
            </div>
            <div className="mt-2.5 text-xs text-ink-3 leading-relaxed">
              判定阈值 {result.threshold}（&gt;{result.threshold} 判 AI 生成，&lt;0.3 判真实，其间不确定）。
              {result.note}；分数为模型估计值，不构成鉴定结论。
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
