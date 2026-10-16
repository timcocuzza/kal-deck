import test from 'node:test'
import assert from 'node:assert/strict'
import { orderedLeaderboard } from '../src/leaderboardOrder.ts'

test('league standings preserve exact server ranks and ties rather than rounded values', () => {
  const teams = [
    { team: 'SEA', rank: 3, value: '0.12' },
    { team: 'BUF', rank: 1, value: '0.12' },
    { team: 'ATL', rank: 1, value: '0.12' },
    { team: 'NE', rank: null, value: null },
  ]
  const result = orderedLeaderboard(teams)
  assert.deepEqual(result.map(team => [team.team, team.rank]), [['ATL', 1], ['BUF', 1], ['SEA', 3], ['NE', null]])
  assert.equal(teams[0].team, 'SEA', 'The shared report must not be mutated')
})

test('unranked and invalid standings remain visible after ranked teams', () => {
  const teams = [{ team: 'SEA' }, { team: 'BUF', rank: NaN }, { team: 'ATL', rank: 2 }, { team: 'NE', rank: 0 }]
  assert.deepEqual(orderedLeaderboard(teams).map(team => team.team), ['ATL', 'BUF', 'NE', 'SEA'])
  assert.deepEqual(orderedLeaderboard([]), [])
})
