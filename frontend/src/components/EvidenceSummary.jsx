export default function EvidenceSummary({ state }) {
  if (state.loading) return <p className="text-xs text-pearl-ink-3">证据资料加载中…</p>
  if (state.error) return <p className="text-xs text-pearl-ink-3">证据资料加载失败，暂不判断。</p>
  if (!state.data) return null
  const profile = state.data
  return (
    <div className="text-sm text-pearl-ink-2">
      <p>{profile.ingredients_with_assertions ?? 0} / {profile.ingredients_total ?? 0} 个成分有挂接资料，共 {profile.assertions_total ?? 0} 条断言。</p>
      <div className="flex flex-wrap gap-2 mt-2">
        {(profile.by_level || []).filter((level) => level.count > 0).map((level) => (
          <span key={level.level} className="pearl-badge-muted">{level.level === 'unknown' ? '未明确分级' : level.label} {level.count}</span>
        ))}
      </div>
      <p className="text-xs text-pearl-ink-3 mt-2">成分关联资料不等同于成品功效验证；分类、安全与供应商资料不能当作临床功效实证。</p>
    </div>
  )
}
