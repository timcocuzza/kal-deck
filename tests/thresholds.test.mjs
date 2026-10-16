import assert from 'node:assert/strict'
import { test } from 'node:test'
import { thresholdHits } from '../src/thresholds.ts'

test('threshold hits include equality and zero, exclude missing and invalid statistics', () => {
  const games = [null, 0, 29, 30, 50, 80, NaN, Infinity].map(value => ({ value }))
  assert.deepEqual(thresholdHits(games, 30), { hits: 3, total: 5 })
  assert.deepEqual(thresholdHits(games, 50), { hits: 2, total: 5 })
  assert.deepEqual(thresholdHits(games, 0), { hits: 5, total: 5 })
  assert.deepEqual(thresholdHits(games, 100), { hits: 0, total: 5 })
})

test('empty and missing-only logs have no eligible games', () => {
  assert.deepEqual(thresholdHits([], 30), { hits: 0, total: 0 })
  assert.deepEqual(thresholdHits([{ value: null }], 30), { hits: 0, total: 0 })
})
