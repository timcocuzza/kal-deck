import assert from 'node:assert/strict'
import { test } from 'node:test'
import { eloMatchup, readElo } from '../src/elo.ts'

const game = { game_id: '2026_06_SEA_DEN', away: { code: 'SEA' }, home: { code: 'DEN' }, neutral: false }
const row = { game_id: game.game_id, season: 2026, away_team: 'SEA', home_team: 'DEN', neutral: false,
  away_expected_score: 0.5270015847723144, home_expected_score: 0.4729984152276856 }
const loaded = { season: 2026, available: true, teams: [], matchups: [row], sources: [], warnings: [] }

test('Elo expectations join only the exact game, season, teams and venue designation', () => {
  assert.equal(eloMatchup(loaded, game), row)
  for (const mismatch of [ { game_id: 'another-game' }, { neutral: true }, { home: { code: 'SEA' }, away: { code: 'DEN' } } ]) {
    assert.equal(eloMatchup(loaded, { ...game, ...mismatch }), undefined)
  }
  assert.equal(eloMatchup({ ...loaded, season: 2025 }, game), undefined)
  assert.equal(eloMatchup({ ...loaded, available: false }, game), undefined)
  assert.equal(eloMatchup(null, game), undefined)
})

test('Elo reader preserves source failure provenance, absence and backend error details', async () => {
  const original = globalThis.fetch
  const signal = new AbortController().signal
  let result = { ...loaded, sources: [{ status: 'refresh_failed', error: 'Provider unavailable', fetched_at: '2026-10-15T00:00:00Z' }] }
  let status = 200
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/elo?season=2026')
    assert.equal(options.signal, signal)
    assert.equal(options.method, undefined, 'Reading Elo must not trigger a refresh')
    return new Response(JSON.stringify(result), { status })
  }
  try {
    assert.deepEqual(await readElo('2026', signal), result)
    result = { ...loaded, available: false, teams: [], matchups: [] }
    assert.deepEqual(await readElo('2026', signal), result)
    result = { detail: 'Incomplete Elo history.' }; status = 422
    await assert.rejects(readElo('2026', signal), { message: 'Incomplete Elo history.', status: 422 })
    result = { ...loaded, season: 2025 }; status = 200
    await assert.rejects(readElo('2026', signal), { status: 422 })
  } finally { globalThis.fetch = original }
})
