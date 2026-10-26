import assert from 'node:assert/strict'
import { test } from 'node:test'
import { historyWindow, historyPath, historyX, historyY, historySnapshot, ensureSpreadHistory, loadSpreadHistory, subscribeHistory } from '../src/spreadHistory.ts'

function data(points = [], end = 7 * 86400 + 300) {
  return { points, fetched_at: '2026-10-15T00:00:00Z', url: 'https://example.test',
    context: { ticker: 'KXNFLSPREAD-TEST', series: 'KXNFLSPREAD', start_ts: end - 7 * 86400, end_ts: end, interval_minutes: 60 } }
}
const point = (timestamp, midpoint = 0.5) => ({ timestamp, midpoint, bid: '0.49', ask: '0.51' })

test('range switching keeps the downloaded window and exposes missing hours', () => {
  const history = data([point(86400 * 7)])
  for (const hours of [168, 24, 6]) {
    const slots = historyWindow(history, hours)
    assert.equal(slots.length, hours)
    assert.equal(slots.at(-1).midpoint, 0.5)
    assert.equal(slots.filter(slot => slot.midpoint === null).length, hours - 1)
    assert.equal(slots.at(-1).timestamp, 86400 * 7)
  }
  assert.equal(history.points.length, 1)
})

test('paths break across absent hours and invalid quotes, preserving isolated points', () => {
  const history = data([point(3600), point(7200), point(14400), point(18000, null), point(21600)], 21900)
  history.context.start_ts = 300
  const slots = historyWindow(history, 6)
  const path = historyPath(slots, 300, 21900)
  assert.equal((path.match(/M/g) ?? []).length, 3)
  assert.equal((path.match(/L/g) ?? []).length, 1)
  assert.equal(historyPath(historyWindow(data(), 6), 1, 2).trim(), '')
})

test('all charts share the same probability and time scales', () => {
  assert.equal(historyY(0), 156)
  assert.equal(historyY(0.5), 86)
  assert.equal(historyY(1), 16)
  assert.equal(historyX(100, 100, 200), 44)
  assert.equal(historyX(200, 100, 200), 464)
})

test('automatic history deduplicates mounts, runs sequentially, and permits explicit retries without retry loops', async () => {
  const originalFetch = globalThis.fetch
  let active = 0
  let maximumActive = 0
  const calls = []
  let fail = false
  let wrongContract = false
  let notifications = 0
  const unsubscribe = subscribeHistory(() => notifications++)
  globalThis.fetch = async url => {
    active++
    maximumActive = Math.max(maximumActive, active)
    calls.push(url)
    await new Promise(resolve => setTimeout(resolve, 5))
    active--
    if (fail) return new Response(JSON.stringify({ detail: 'Simulated source failure' }), { status: 502 })
    const parsed = new URL(url, 'http://localhost')
    const ticker = parsed.pathname.split('/').at(-2)
    const result = data()
    result.context = { ...result.context, ticker: wrongContract ? 'OTHER' : ticker,
      start_ts: Number(parsed.searchParams.get('start')), end_ts: Number(parsed.searchParams.get('end')) }
    return new Response(JSON.stringify(result))
  }
  try {
    assert.equal(calls.length, 0)
    const first = ensureSpreadHistory(['KXNFLSPREAD-A', 'KXNFLSPREAD-B', 'KXNFLSPREAD-A'])
    const repeated = ensureSpreadHistory(['KXNFLSPREAD-A'])
    assert.equal(historySnapshot()['KXNFLSPREAD-A'].status, 'queued')
    await Promise.all([first, repeated])
    assert.equal(calls.length, 2)
    assert.equal(maximumActive, 1)
    await ensureSpreadHistory(['KXNFLSPREAD-A', 'KXNFLSPREAD-B'])
    assert.equal(calls.length, 2, 'returning to downloaded cards reuses history')
    const saved = historySnapshot()['KXNFLSPREAD-A'].data
    fail = true
    await loadSpreadHistory(['KXNFLSPREAD-A'])
    assert.equal(historySnapshot()['KXNFLSPREAD-A'].data, saved)
    assert.equal(historySnapshot()['KXNFLSPREAD-A'].error, 'Simulated source failure')
    assert.equal(historySnapshot()['KXNFLSPREAD-A'].status, undefined)
    await ensureSpreadHistory(['KXNFLSPREAD-A'])
    assert.equal(calls.length, 3, 'failed refreshes do not trigger automatic retry loops')
    await ensureSpreadHistory(['KXNFLSPREAD-FAILED'])
    assert.equal(calls.length, 4)
    await ensureSpreadHistory(['KXNFLSPREAD-FAILED'])
    assert.equal(calls.length, 4, 'initial failures also wait for an explicit retry')
    fail = false
    wrongContract = true
    await loadSpreadHistory(['KXNFLSPREAD-A'])
    assert.equal(historySnapshot()['KXNFLSPREAD-A'].data, saved)
    assert.match(historySnapshot()['KXNFLSPREAD-A'].error, /does not match/)
    wrongContract = false
    await loadSpreadHistory(['KXNFLSPREAD-A'])
    assert.equal(historySnapshot()['KXNFLSPREAD-A'].error, undefined)
    assert.ok(notifications >= 12)
  } finally {
    unsubscribe()
    globalThis.fetch = originalFetch
  }
})

test('college history uses its own series, rejects mismatches, and preserves valid prior data', async () => {
  const originalFetch = globalThis.fetch
  const ticker = 'KXNCAAFSPREAD-26OCT24BYUUCF-BYU8'
  const calls = []
  let wrongSeries = false
  globalThis.fetch = async url => {
    calls.push(url)
    const parsed = new URL(url, 'http://localhost')
    assert.equal(parsed.pathname, `/api/markets/KXNCAAFSPREAD/${ticker}/history`)
    const result = data()
    result.context = { ...result.context, ticker, series: wrongSeries ? 'KXNFLSPREAD' : 'KXNCAAFSPREAD',
      start_ts: Number(parsed.searchParams.get('start')), end_ts: Number(parsed.searchParams.get('end')) }
    return new Response(JSON.stringify(result))
  }
  try {
    await ensureSpreadHistory([ticker, ticker])
    assert.equal(calls.length, 1)
    const saved = historySnapshot()[ticker].data
    assert.equal(saved.context.series, 'KXNCAAFSPREAD')
    wrongSeries = true
    await loadSpreadHistory([ticker])
    assert.equal(historySnapshot()[ticker].data, saved)
    assert.match(historySnapshot()[ticker].error, /does not match/)
    await ensureSpreadHistory([ticker])
    assert.equal(calls.length, 2)
  } finally { globalThis.fetch = originalFetch }
})
