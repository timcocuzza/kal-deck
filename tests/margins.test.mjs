import test from 'node:test'
import assert from 'node:assert/strict'
import { assessMarginForecast, contractDifference, differenceLabel, modelLabel, MAX_SOURCE_AGE_MS } from '../src/margins.ts'
import { watchMarginClock } from '../src/margins.ts'
const downloaded = Date.now()
const forecast = { available: true, home_margin: 10.2, home_team_id: 'OSU', away_team_id: 'MICH',
  prediction_as_of: new Date(downloaded).toISOString(), training_cutoff: '2026-10-20T00:00:00Z',
  source_freshness: [{ name: 'schedule', fetched_at: new Date(downloaded).toISOString(), status: 'fresh', error: null }] }
const contract = { team_id: 'OSU', threshold: 7.5, operator: 'gt', no_push: true }
test('structured home and away contracts, changed selection, and signed gaps', () => {
  assert.ok(Math.abs(contractDifference(forecast, contract) - 2.7) < 1e-10)
  assert.equal(contractDifference(forecast, { ...contract, team_id: 'MICH' }), -17.7)
  assert.ok(Math.abs(contractDifference(forecast, { ...contract, threshold: 14.5 }) + 4.3) < 1e-10)
  assert.ok(Math.abs(contractDifference({ ...forecast, home_margin: -10.2 }, { ...contract, team_id: 'MICH' }) - 2.7) < 1e-10)
})
test('unavailable, malformed settlement, unknown teams, and nonfinite values fail closed', () => {
  for (const f of [undefined, { ...forecast, available: false }, { ...forecast, home_margin: null }, { ...forecast, home_margin: NaN }]) assert.equal(contractDifference(f, contract), null)
  for (const c of [undefined, { ...contract, team_id: 'unknown' }, { ...contract, threshold: 7 }, { ...contract, operator: 'gte' }, { ...contract, no_push: false }]) assert.equal(contractDifference(forecast, c), null)
})
test('exact strict half-point threshold has a zero model difference, not a push claim', () => {
  assert.equal(contractDifference({ ...forecast, home_margin: 7.5 }, contract), 0)
  assert.equal(differenceLabel(0), 'At threshold (0.0 points)')
  assert.equal(modelLabel(10.2, 'Ohio State', 'Michigan'), 'Ohio State by 10.2')
  assert.equal(modelLabel(-10.2, 'Ohio State', 'Michigan'), 'Michigan by 10.2')
  assert.equal(modelLabel(-0.001, 'Ohio State', 'Michigan'), 'Even matchup (0.0 points)')
})

test('cached successful responses expire at source age, never prediction or training time', () => {
  const boundary = downloaded + MAX_SOURCE_AGE_MS
  assert.equal(assessMarginForecast(forecast, boundary).available, true)
  const stale = assessMarginForecast(forecast, boundary + 1)
  assert.equal(stale.available, false)
  assert.equal(stale.home_margin, null)
  assert.match(stale.unavailable_reason, /older than 24 hours/)
  assert.equal(stale.source_freshness[0].status, 'stale')
  assert.equal(stale.prediction_as_of, forecast.prediction_as_of)
  assert.equal(stale.training_cutoff, forecast.training_cutoff)
  assert.equal(forecast.available, true, 'the shared report cache must remain immutable')
  assert.equal(contractDifference(forecast, contract, boundary + 1), null)
  assert.equal(assessMarginForecast({ ...forecast, prediction_as_of: new Date(boundary).toISOString() }, boundary + 1).available, false)
})

test('oldest input governs expiry; missing, future, naive timestamps and failed refreshes fail honestly', () => {
  for (const fetched_at of [null, 'bad', '2026-10-27T12:00:00', new Date(downloaded + 1).toISOString()]) {
    assert.equal(assessMarginForecast({ ...forecast, source_freshness: [{ fetched_at }] }, downloaded).available, false)
  }
  assert.equal(assessMarginForecast({ ...forecast, source_freshness: [] }).available, false)
  const failed = { ...forecast, source_freshness: [{ ...forecast.source_freshness[0], error: 'offline' }] }
  assert.equal(assessMarginForecast(failed, downloaded).available, true)
  assert.equal(assessMarginForecast(failed, downloaded + MAX_SOURCE_AGE_MS + 1).available, false)
  const mixed = { ...forecast, source_freshness: [...forecast.source_freshness, { fetched_at: new Date(downloaded - MAX_SOURCE_AGE_MS - 1).toISOString() }] }
  assert.equal(assessMarginForecast(mixed, downloaded).available, false)
  const refused = { ...forecast, available: false, home_margin: null, unavailable_reason: 'FCS ratings are withheld.' }
  assert.equal(assessMarginForecast(refused, downloaded).available, false)
  assert.equal(assessMarginForecast(refused, downloaded + MAX_SOURCE_AGE_MS + 1).unavailable_reason, refused.unavailable_reason)
})

test('an already-open view updates across expiry and immediately on resume, with cleanup', t => {
  const boundary = downloaded + MAX_SOURCE_AGE_MS
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: boundary - 100 })
  const windowEvents = new EventTarget(), documentEvents = new EventTarget()
  const renders = []
  const stop = watchMarginClock(forecast, () => renders.push(assessMarginForecast(forecast).available), windowEvents, documentEvents)
  t.mock.timers.tick(100)
  assert.deepEqual(renders, [])
  t.mock.timers.tick(1)
  assert.deepEqual(renders, [false])
  // Suspended background timers need not run before focus/visibility is restored.
  t.mock.timers.setTime(boundary + 3 * MAX_SOURCE_AGE_MS)
  windowEvents.dispatchEvent(new Event('focus'))
  documentEvents.dispatchEvent(new Event('visibilitychange'))
  windowEvents.dispatchEvent(new Event('pageshow'))
  assert.deepEqual(renders, [false, false, false, false])
  stop()
  t.mock.timers.tick(120_000)
  windowEvents.dispatchEvent(new Event('focus'))
  assert.equal(renders.length, 4)
})
