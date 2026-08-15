import { useEffect, useMemo, useState } from 'react'
import { Loading } from './common'

// —— 透明匹配分（v2.2 方案，纯前端计算，零新后端）——
// 规则（逐项可展开看依据，非黑盒）：
//   1. 诉求命中且有真人级证据 +20/项
//   2. 命中项剂量达标 +10/项（浓度为模型估计值）
//   3. 敏感肌含酒精/香精/高浓度酸 -15/项（成分名规则匹配，口径见下）
//   4. 每起效成本低于同诉求中位 +10（需跨产品中位统计，一期前端不可得 → 不参与计分，如实灰显）
//   5. 无成分证据支撑的宣称 -10/项
// 肤质档案存 localStorage「yj_profile」= {skin, goals}；算出的分缓存「yj_match_{id}」供列表角标用。

const PROFILE_KEY = 'yj_profile'

// 诉求 → 规范功效族 / 宣称关键词映射（写死规则，口径透明）
const GOALS = ['美白', '抗老', '保湿', '祛痘']
const GOAL_FAMILIES = {
  美白: ['美白'],
  抗老: ['抗皱', '紧致', '抗氧化'],
  保湿: ['保湿'],
  祛痘: ['控油祛痘'],
}
const GOAL_CLAIM_KW = {
  美白: ['美白', '淡斑', '祛斑', '提亮'],
  抗老: ['抗皱', '紧致', '抗老', '抗衰', '淡纹'],
  保湿: ['保湿', '补水'],
  祛痘: ['祛痘', '控油', '粉刺', '清痘'],
}
const SKINS = ['干', '油', '混合', '敏感']

// 真人级证据口径：指纹明细中未排除断言且证据强度 ≥ 0.55（= 人体开放试验及以上层级，
// 法规类 0.9 已被指纹 purity 规则排除）；或宣称备案为「人体功效评价试验 / 消费者使用测试」
const HUMAN_STRENGTH_MIN = 0.55
const HUMAN_CLAIM_CATS = ['人体功效评价试验', '消费者使用测试']

// 敏感肌扣分项成分清单（INCI/中文名规则匹配，写死常量；高浓度酸 = 推断区间中点 ≥ 2%，估计）
const norm = (s) => (s || '').toUpperCase().replace(/[.\s]/g, '')
const ALCOHOL_SET = new Set(['ALCOHOL', 'ALCOHOLDENAT', 'SDALCOHOL', 'ETHANOL', '变性乙醇', '乙醇'])
const ACID_SET = new Set([
  'GLYCOLICACID', 'SALICYLICACID', 'LACTICACID', 'MANDELICACID', 'AZELAICACID',
  'MALICACID', 'TARTARICACID', '乙醇酸', '水杨酸', '乳酸', '扁桃酸', '杏仁酸', '壬二酸', '苹果酸', '酒石酸',
])
const ACID_HIGH_PCT = 2
const isFragrance = (ing) =>
  norm(ing.inci_name).includes('FRAGRANCE') || norm(ing.inci_name).includes('PARFUM') ||
  (ing.cn_name || '').includes('香精')

export function readProfile() {
  try {
    const p = JSON.parse(localStorage.getItem(PROFILE_KEY))
    if (p && SKINS.includes(p.skin) && Array.isArray(p.goals)) return p
  } catch { /* 损坏档案视为未设置 */ }
  return null
}

const stem = (s) => (s || '').split(/[（(]/)[0].trim()
const hitGoal = (text, goal) => GOAL_CLAIM_KW[goal].some((kw) => stem(text).includes(kw))

// —— 规则计算：返回 { score, rows, unavailable } ——
function computeScore({ product, conc, fpData, profile }) {
  const rows = []
  const unavailable = []
  const claims = product.claims || []
  const fingerprint = fpData?.fingerprint || {}
  const detail = fpData?.detail || []
  const families = new Set(Object.keys(fingerprint))
  const estimates = conc.data?.inferred ? conc.data.estimates : null

  // 规则 1+2：逐诉求
  for (const goal of profile.goals) {
    const fams = GOAL_FAMILIES[goal]
    const famHit = fams.filter((f) => families.has(f))
    const claimHit = claims.filter((c) => hitGoal(c.claim, goal))
    if (famHit.length === 0 && claimHit.length === 0) {
      unavailable.push(`诉求「${goal}」：功效指纹与宣称中均未命中，不计分`)
      continue
    }
    // 真人级证据：指纹明细（未排除、强度达标、族命中）或宣称人体测试
    const humanAssertions = detail.filter(
      (d) => !d.excluded && fams.includes(d.efficacy_canonical) &&
        (d.evidence_strength ?? 0) >= HUMAN_STRENGTH_MIN
    )
    const humanClaims = claimHit.filter((c) => HUMAN_CLAIM_CATS.includes(c.eval_category))
    if (humanAssertions.length > 0 || humanClaims.length > 0) {
      const basis = [
        ...humanAssertions.slice(0, 3).map(
          (d) => `${d.inci_name}｜${d.efficacy}（证据强度 ${d.evidence_strength}，人体试验层级）`
        ),
        ...humanClaims.map((c) => `宣称「${c.claim}」备案为${c.eval_category}${c.institution ? `（${c.institution}）` : ''}`),
      ]
      rows.push({ delta: 20, label: `诉求「${goal}」命中且有真人级证据`, basis })
    } else {
      unavailable.push(`诉求「${goal}」命中（${[...famHit, ...claimHit.map((c) => c.claim)].join('、')}），但无真人级证据，不加 20 分`)
    }
    // 剂量达标（仅对有浓度推断的产品可判定）
    if (estimates) {
      const eff = []
      for (const est of estimates) {
        for (const d of est.dose || []) {
          if (d.verdict === 'effective' && hitGoal(d.efficacy, goal)) {
            eff.push({ est, d })
          }
        }
      }
      if (eff.length > 0) {
        rows.push({
          delta: 10,
          label: `诉求「${goal}」剂量达标（估计）`,
          basis: eff.slice(0, 3).map(({ est, d }) =>
            `${est.inci_name} 推断 ${est.low}–${est.high}% ≥ 起效线 ${d.eff_low}%（${d.efficacy}，估计值）`
          ),
        })
      }
    }
  }

  // 规则 3：敏感肌扣分（成分名规则匹配）
  if (profile.skin === '敏感') {
    const ings = product.ingredients || []
    const alcohol = ings.filter((i) => ALCOHOL_SET.has(norm(i.inci_name)) || ALCOHOL_SET.has(i.cn_name))
    const fragrance = ings.filter(isFragrance)
    const acidAll = ings.filter((i) => ACID_SET.has(norm(i.inci_name)) || ACID_SET.has(i.cn_name))
    const byInci = new Map((estimates || []).map((e) => [norm(e.inci_name), e]))
    const acidHigh = estimates
      ? acidAll.filter((i) => {
          const e = byInci.get(norm(i.inci_name))
          return e && (e.low + e.high) / 2 >= ACID_HIGH_PCT
        })
      : []
    const cats = [
      ['酒精', alcohol],
      ['香精', fragrance],
      ['高浓度酸', acidHigh],
    ]
    for (const [cat, list] of cats) {
      if (list.length > 0) {
        rows.push({
          delta: -15,
          label: `敏感肌：含${cat}`,
          basis: list.map((i) => `${i.cn_name || i.inci_name}（${i.inci_name}）`),
        })
      }
    }
    if (acidAll.length > 0 && !estimates) {
      unavailable.push(`含酸类成分 ${acidAll.length} 个，但无浓度推断，「高浓度酸」无法判定不扣分`)
    }
  }

  // 规则 4：跨产品中位统计一期前端不可得，如实灰显不参与
  unavailable.push('每起效成本低于同诉求中位 +10：需跨产品中位统计，一期暂不参与计分')

  // 规则 5：无成分证据支撑的宣称 -10/项（宣称本身有备案检测方法，此处指成分证据库无对应功效族）
  for (const c of claims) {
    const s = stem(c.claim)
    const supported = [...families].some((f) => f !== '其他' && (s.includes(f) || f.includes(s)))
    if (!supported) {
      rows.push({
        delta: -10,
        label: `宣称「${c.claim}」无成分证据支撑`,
        basis: [`功效指纹各规范族中无「${s}」对应断言（宣称本身的备案方法：${c.eval_category || '未公示'}）`],
      })
    }
  }

  const raw = rows.reduce((sum, r) => sum + r.delta, 0)
  return { score: Math.min(Math.max(raw, 0), 100), raw, rows, unavailable }
}

function RuleRow({ r }) {
  const [open, setOpen] = useState(false)
  const pos = r.delta > 0
  return (
    <div className="fairy-panel px-3.5 py-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <span className="text-[13px] text-pearl-ink">{r.label}</span>
        <span className="flex items-center gap-2 shrink-0">
          <span className={`font-num font-semibold tabular-nums ${pos ? 'text-[#3d7a54]' : 'text-[#a04a4a]'}`}>
            {pos ? '+' : ''}{r.delta}
          </span>
          <span className="text-pearl-ink-3 text-xs">{open ? '收起 ▴' : '依据 ▾'}</span>
        </span>
      </button>
      {open && (
        <ul className="mt-2 pt-2 border-t border-[rgba(138,90,106,0.15)] space-y-1">
          {r.basis.map((b, i) => (
            <li key={i} className="text-xs text-pearl-ink-2 leading-relaxed">· {b}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ProfileModal({ initial, onSave, onClose }) {
  const [skin, setSkin] = useState(initial?.skin || '干')
  const [goals, setGoals] = useState(initial?.goals || [])
  const toggle = (g) => setGoals((gs) => (gs.includes(g) ? gs.filter((x) => x !== g) : [...gs, g]))
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30" onClick={onClose}>
      <div className="glass-card w-full max-w-md !mb-0" onClick={(e) => e.stopPropagation()}>
        <h3 className="pearl-title">设置我的肤质与诉求</h3>
        <div className="text-xs text-pearl-ink-3 mb-2">肤质（单选）</div>
        <div className="flex flex-wrap gap-2">
          {SKINS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSkin(s)}
              className={skin === s ? 'fairy-chip ring-2 ring-rosewood/50' : 'pearl-badge-muted'}
            >
              {s}皮
            </button>
          ))}
        </div>
        <div className="text-xs text-pearl-ink-3 mt-4 mb-2">诉求（多选）</div>
        <div className="flex flex-wrap gap-2">
          {GOALS.map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => toggle(g)}
              className={goals.includes(g) ? 'fairy-chip ring-2 ring-rosewood/50' : 'pearl-badge-muted'}
            >
              {g}
            </button>
          ))}
        </div>
        <div className="mt-6 flex gap-3">
          <button type="button" className="btn-fairy flex-1" onClick={() => onSave({ skin, goals })}>
            保存
          </button>
          <button type="button" className="btn-fairy-ghost" onClick={onClose}>取消</button>
        </div>
        <div className="mt-3 text-xs text-pearl-ink-3 leading-relaxed">
          仅保存在本机浏览器（localStorage），不上传；随时可改。
        </div>
      </div>
    </div>
  )
}

export default function MatchScore({ product, conc, fp }) {
  const [profile, setProfile] = useState(readProfile)
  const [modalOpen, setModalOpen] = useState(false)

  const ready = !conc.loading && !fp.loading && profile
  const result = useMemo(
    () => (ready ? computeScore({ product, conc, fpData: fp.data, profile }) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ready, product.id, conc.data, fp.data, profile]
  )

  // 缓存得分供产品库卡片角标使用（纯 localStorage，零额外请求）
  useEffect(() => {
    if (result && profile) {
      try {
        localStorage.setItem(`yj_match_${product.id}`, JSON.stringify({ score: result.score }))
      } catch { /* 存储不可用时跳过角标缓存 */ }
    }
  }, [result, profile, product.id])

  const saveProfile = (p) => {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(p))
    setProfile(p)
    setModalOpen(false)
  }

  const insufficient = product.claims.length === 0 && !conc.data?.inferred

  return (
    <div className="glass-card">
      <h2 className="pearl-title">透明匹配分</h2>
      {!profile ? (
        <div className="text-center py-4">
          <div className="text-sm text-pearl-ink-2 mb-4">告诉我你的肤质与诉求，逐项可复核地算一个匹配分。</div>
          <button type="button" className="btn-fairy" onClick={() => setModalOpen(true)}>
            设置我的肤质
          </button>
        </div>
      ) : !ready ? (
        <Loading />
      ) : insufficient ? (
        <div className="pearl-notice !mb-0">数据不足，仅供参考（无宣称摘要且无浓度推断）——不给分，不猜测。</div>
      ) : (
        <>
          <div className="flex items-end justify-between flex-wrap gap-3">
            <div>
              <span className="font-num text-5xl font-bold grad-text">{result.score}</span>
              <span className="text-pearl-ink-3 text-sm ml-1">/ 100</span>
            </div>
            <button type="button" className="btn-fairy-ghost !px-4 !py-1.5 text-xs" onClick={() => setModalOpen(true)}>
              {profile.skin}皮 · {profile.goals.join('、') || '未选诉求'} ✎
            </button>
          </div>
          {result.raw !== result.score && (
            <div className="mt-1 text-xs text-pearl-ink-3">原始累加 {result.raw} 分，展示截断到 0–100。</div>
          )}
          <div className="mt-4 space-y-2">
            {result.rows.length === 0 && (
              <div className="text-xs text-pearl-ink-3 py-1">当前档案下无触发的加减分项。</div>
            )}
            {result.rows.map((r, i) => <RuleRow key={i} r={r} />)}
          </div>
          {result.unavailable.length > 0 && (
            <div className="mt-3 space-y-1">
              {result.unavailable.map((u, i) => (
                <div key={i} className="text-xs text-pearl-ink-3 leading-relaxed">· {u}</div>
              ))}
            </div>
          )}
          <div className="mt-4 text-xs text-pearl-ink-3 leading-relaxed">
            透明匹配分：每条加减分可展开复核，非黑盒推荐。真人级 = 证据强度 ≥0.55（人体试验层级）
            或宣称备案为人体功效评价/消费者测试；剂量与「高浓度酸」（推断中点 ≥2%）均为估计值；
            敏感肌项按成分名规则匹配（酒精/香精/酸类清单为组件内固定常量）。
          </div>
        </>
      )}
      {modalOpen && <ProfileModal initial={profile} onSave={saveProfile} onClose={() => setModalOpen(false)} />}
    </div>
  )
}
