// Shared POST SSE reader. A clean HTTP EOF is distinct from the protocol's [DONE].
export async function streamRoundtable(productName, signal, onEvent, productId = null) {
  const response = await fetch('/api/roundtable', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ product_name: productName, ...(productId ? { product_id: productId } : {}) }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const error = new Error(payload.detail || `HTTP ${response.status}`)
    error.status = response.status
    throw error
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      let match
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, match.index)
        buffer = buffer.slice(match.index + match[0].length)
        const payload = block.split(/\r?\n/).filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trimStart()).join('\n').trim()
        if (payload === '[DONE]') return 'done'
        if (!payload) continue
        // Parse errors are protocol errors; handler errors must also propagate.
        const event = JSON.parse(payload)
        if (!signal?.aborted) onEvent(event)
      }
      if (done) return 'eof'
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
