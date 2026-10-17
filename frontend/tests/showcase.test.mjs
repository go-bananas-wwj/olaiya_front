import test from 'node:test'
import assert from 'node:assert/strict'
import { chartScale, comparableUnitPrices, ingredientRows, compareIngredients, sortCandidates } from '../src/showcase/logic.mjs'
import { streamRoundtable } from '../src/showcase/stream.mjs'

test('price sort uses comparable units, missing prices follow, input unchanged', () => {
  const rows = [
    { id: 1, unit_price: 2, unit_price_unit: 'g' },
    { id: 2, unit_price: null },
    { id: 3, unit_price: 5, unit_price_unit: 'ml' },
    { id: 4, unit_price: 1, unit_price_unit: 'ml' },
  ]
  assert.deepEqual(sortCandidates(rows, 'price', 'ml').map(x => x.id), [4, 3, 1, 2])
  assert.deepEqual(rows.map(x => x.id), [1, 2, 3, 4])
  assert.deepEqual(sortCandidates(rows, 'price', null), rows)
})

test('ingredient comparison uses identity, not translations or list order', () => {
  const a = [{ ingredient_id: 1 }, { ingredient_id: 2 }]
  const b = [{ ingredient_id: 2 }, { ingredient_id: 3 }]
  const result = compareIngredients(a, b)
  assert.deepEqual(result.shared, [a[1]])
  assert.deepEqual(result.onlyTarget, [a[0]])
  assert.deepEqual(result.onlyCandidate, [b[1]])
})

test('one chart scale spans both products and preserves zero versus missing values', () => {
  assert.equal(chartScale([{ dimensions: [{ score: 0.8 }, { score: null }] }, { dimensions: [{ score: 2.8 }] }]), 3)
  assert.equal(chartScale([{ dimensions: [{ score: 0 }] }]), 1)
  assert.equal(chartScale([null, undefined]), 1)
})

test('ingredient rows distinguish not listed from unknown order and deduplicate IDs', () => {
  const a = [{ ingredient_id: 1, position: null }, { ingredient_id: 2, position: 1 }]
  const b = [{ ingredient_id: 2, position: 4 }, { ingredient_id: 3, position: null }]
  const rows = ingredientRows(a, b, 'differences')
  assert.deepEqual(rows.map(r => r.ingredient_id), [1, 3])
  assert.equal(rows[0].a.position, null)
  assert.equal(rows[0].b, undefined)
  assert.equal(ingredientRows(a, b, 'shared')[0].a.position, 1)
  assert.equal(ingredientRows([...a, a[0]], b, 'all').length, 3)
})

test('unit-price graph requires known matching units and accepts real zero', () => {
  const a = { unit_price: 0, unit_price_unit: 'ml' }
  assert.equal(comparableUnitPrices(a, { unit_price: 2, unit_price_unit: 'ml' }), true)
  assert.equal(comparableUnitPrices(a, { unit_price: 2, unit_price_unit: 'g' }), false)
  assert.equal(comparableUnitPrices(a, { unit_price: null, unit_price_unit: 'ml' }), false)
})

test('roundtable handles split UTF-8 / CRLF and sends selected product ID', async () => {
  const originalFetch = globalThis.fetch
  let body
  const bytes = new TextEncoder().encode('data: {"event":"speak","content":"证据"}\r\n\r\ndata: [DONE]\r\n\r\n')
  globalThis.fetch = async (_, options) => {
    body = JSON.parse(options.body)
    return new Response(new ReadableStream({ start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
      controller.close()
    } }))
  }
  try {
    const events = []
    const result = await streamRoundtable('selected', new AbortController().signal, e => events.push(e), 73)
    assert.equal(body.product_id, 73)
    assert.equal(result, 'done')
    assert.equal(events[0].content, '证据')
  } finally { globalThis.fetch = originalFetch }
})

test('roundtable distinguishes truncated stream and does not swallow callback errors', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('data: {"event":"start"}\n\n')
  try {
    assert.equal(await streamRoundtable('x', null, () => {}, 1), 'eof')
    await assert.rejects(streamRoundtable('x', null, () => { throw new Error('handler failure') }, 1), /handler failure/)
  } finally { globalThis.fetch = originalFetch }
})
