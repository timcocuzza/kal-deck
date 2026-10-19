import assert from 'node:assert/strict'
import { test } from 'node:test'
import { watchAsk, watchOutcome } from '../src/watchlistStatus.ts'

test('hit/miss compares the saved side with the official result', () => {
  for (const side of ['Yes', 'No']) {
    for (const result of ['yes', 'no']) {
      assert.equal(watchOutcome(side, { result }).tone, side.toLowerCase() === result ? 'hit' : 'miss')
    }
  }
  assert.equal(watchOutcome('Yes', {}), null)
  assert.equal(watchOutcome('No'), null)
  assert.deepEqual(watchOutcome('', { result: 'no' }), { tone: 'neutral', label: 'Resolved No · no side chosen' })
  for (const result of ['scalar', 'void']) assert.equal(watchOutcome('Yes', { result }).tone, 'neutral')
})

test('side changes select independently retained asks without fabricating a missing No ask', () => {
  const tracking = { yes_ask: { dollars: '0.45', fetched_at: '2026-10-18T16:58:00Z' } }
  assert.equal(watchAsk('', tracking), tracking.yes_ask)
  assert.equal(watchAsk('Yes', tracking), tracking.yes_ask)
  assert.equal(watchAsk('No', tracking), undefined)
  tracking.no_ask = { dollars: '0.58', fetched_at: '2026-10-18T16:59:00Z' }
  assert.equal(watchAsk('No', tracking), tracking.no_ask)
})
