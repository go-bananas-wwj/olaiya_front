// API 访问层：同源相对路径，vite dev 下经 proxy 转发到 :8000
async function get(path, params = {}) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, v)
  }
  const url = qs.toString() ? `${path}?${qs}` : path
  const res = await fetch(url)
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const body = await res.json()
      if (body && body.detail) detail = body.detail
    } catch { /* 非 JSON 错误体 */ }
    throw new Error(detail)
  }
  return res.json()
}

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const payload = await res.json()
      if (payload && payload.detail) {
        detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
      }
    } catch { /* 非 JSON 错误体 */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

async function postFile(path, file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(path, { method: 'POST', body: fd })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const payload = await res.json()
      if (payload && payload.detail) {
        detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
      }
    } catch { /* 非 JSON 错误体 */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  stats: () => get('/api/stats'),
  products: (params) => get('/api/products', params), // q / brand / has_claims / limit
  product: (id) => get(`/api/products/${id}`),
  productConcentration: (id) => get(`/api/products/${id}/concentration`),
  productSimilarLevels: (id, params) => get(`/api/products/${id}/similar-levels`, params), // k
  ingredients: (params) => get('/api/ingredients', params), // q / has_evidence
  ingredient: (id) => get(`/api/ingredients/${id}`),
  chat: (question) => post('/api/chat', { question }),
  detectImage: (file) => postFile('/api/detect-image', file),
}
