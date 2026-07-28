// Intro-sequence helpers: cubic-bezier easing solver + shared constants.

export const INTRO_KEY = 'cz-hero-intro-v1'

// Evaluate CSS-style cubic-bezier(x1, y1, x2, y2) at x via Newton + bisection.
export function cubicBezier(x1, y1, x2, y2) {
  const ax = 3 * x1 - 3 * x2 + 1
  const bx = 3 * x2 - 6 * x1
  const cx = 3 * x1
  const ay = 3 * y1 - 3 * y2 + 1
  const by = 3 * y2 - 6 * y1
  const cy = 3 * y1
  const sx = (t) => ((ax * t + bx) * t + cx) * t
  const sy = (t) => ((ay * t + by) * t + cy) * t
  const sdx = (t) => (3 * ax * t + 2 * bx) * t + cx
  return (x) => {
    let t = Math.min(1, Math.max(0, x))
    for (let i = 0; i < 8; i++) {
      const err = sx(t) - x
      if (Math.abs(err) < 1e-6) return sy(t)
      const d = sdx(t)
      if (Math.abs(d) < 1e-6) break
      t -= err / d
      if (t < 0) t = 0
      if (t > 1) t = 1
    }
    let lo = 0
    let hi = 1
    t = x
    for (let i = 0; i < 32; i++) {
      const v = sx(t)
      if (Math.abs(v - x) < 1e-6) break
      if (v < x) lo = t
      else hi = t
      t = (lo + hi) / 2
    }
    return sy(t)
  }
}

// cubic-bezier(0.65, 0, 0.35, 1) — the doc's ease-in-out for the dolly.
export const easeInOut = cubicBezier(0.65, 0, 0.35, 1)

export const easeOutBack = (t) => {
  const c1 = 1.70158
  const c3 = c1 + 1
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2)
}
