import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadReport, reportSnapshot } from '../src/useReport.ts'

test('saved reports deduplicate navigation reads, retain data on failure and isolate seasons', async () => {
  const original = globalThis.fetch
  let calls = 0, fail = false, invalid = false, release
  const gate = new Promise(resolve => { release = resolve })
  globalThis.fetch = async url => {
    calls++
    await gate
    if (fail) throw new Error('Local service disconnected')
    if (invalid) return new Response(JSON.stringify({ detail: 'Invalid saved history' }), { status: 422 })
    return new Response(JSON.stringify({ season: url.includes('2025') ? 2025 : 2026, teams: [{ team: 'SEA', rank: 1 }] }))
  }
  try {
    const url = '/api/test-rankings?season=2026'
    const first = loadReport(url, 0), duplicate = loadReport(url, 0)
    assert.equal(calls, 1)
    assert.equal(reportSnapshot(url).loading, true)
    release()
    await Promise.all([first, duplicate])
    const saved = reportSnapshot(url).data
    assert.equal(saved.season, 2026)
    await loadReport(url, 0)
    assert.equal(calls, 1, 'Returning to a view reuses saved data')
    fail = true
    const update = loadReport(url, 1)
    assert.equal(reportSnapshot(url).data, saved, 'Refreshing keeps content visible')
    await update
    assert.equal(reportSnapshot(url).data, saved)
    assert.equal(reportSnapshot(url).error, 'Local service disconnected')
    fail = false
    await loadReport('/api/test-rankings?season=2025', 1)
    assert.equal(reportSnapshot('/api/test-rankings?season=2025').data.season, 2025)
    assert.equal(reportSnapshot(url).data.season, 2026)
    invalid = true
    await loadReport(url, 2)
    assert.equal(reportSnapshot(url).data, null, 'Invalid data must not remain presented as usable')
    assert.equal(reportSnapshot(url).error, 'Invalid saved history')
  } finally { globalThis.fetch = original }
})

test('a newer revision queued behind an in-flight read is loaded once', async () => {
  const original = globalThis.fetch
  let calls = 0, release
  const gate = new Promise(resolve => { release = resolve })
  globalThis.fetch = async () => {
    const version = ++calls
    if (version === 1) await gate
    return new Response(JSON.stringify({ version }))
  }
  try {
    const url = '/api/test-report-concurrency'
    const first = loadReport(url, 0)
    const next = loadReport(url, 1)
    const duplicate = loadReport(url, 1)
    release()
    await Promise.all([first, next, duplicate])
    assert.equal(calls, 2)
    assert.deepEqual(reportSnapshot(url).data, { version: 2 })
    assert.equal(reportSnapshot(url).loading, false)
  } finally { globalThis.fetch = original }
})
