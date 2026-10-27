import test from 'node:test'
import assert from 'node:assert/strict'
import { contractDifference, differenceLabel, modelLabel } from '../src/margins.ts'
const forecast = { available: true, home_margin: 10.2, home_team_id: 'OSU', away_team_id: 'MICH' }
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
