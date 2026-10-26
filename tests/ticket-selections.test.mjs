import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ticketSelections } from '../src/ticketSelections.ts'

const spread = { leg: { description: 'SEA -2.5', selection: 'No', market_ticker: 'SPREAD-SEA', game_id: '2026_06_SEA_DEN' }, notes: 'Weather concern\nCheck injury report.' }
const prop = { leg: { description: 'Receiver · Receiving yards · 50+', selection: 'Yes', market_ticker: 'PROP-50', game_id: '2026_06_BUF_NYJ' }, notes: 'Strong target share.' }

test('a watchlist combo carries sides, exact references and attributed multiline notes across games', () => {
  const result = ticketSelections([spread, prop])
  assert.equal(result.kind, 'combo')
  assert.deepEqual(result.legs, [spread.leg, prop.leg])
  assert.equal(result.notes, `${spread.leg.description} · No\n${spread.notes}\n\n${prop.leg.description} · Yes\n${prop.notes}`)
  result.legs[0].selection = 'Yes'
  assert.equal(spread.leg.selection, 'No', 'Ticket edits must not change saved watchlist details')
})

test('a single keeps its notes and empty notes do not produce filler', () => {
  assert.deepEqual(ticketSelections([spread]), { legs: [spread.leg], notes: spread.notes, kind: 'single' })
  assert.equal(ticketSelections([{ leg: spread.leg }, { leg: prop.leg, notes: '' }]).notes, '')
})

test('adding picks preserves existing legs and notes and removes only wholly empty placeholder legs', () => {
  const manual = { description: 'Manual market', selection: 'Over', market_ticker: '', game_id: '' }
  const existing = { legs: [manual, { description: '', selection: '', market_ticker: '', game_id: '' }], notes: 'Original ticket notes' }
  const before = structuredClone(existing)
  const result = ticketSelections([spread, prop], existing)
  assert.deepEqual(result.legs, [manual, spread.leg, prop.leg])
  assert.equal(result.notes, `Original ticket notes\n\n${spread.leg.description} · No\n${spread.notes}\n\n${prop.leg.description} · Yes\n${prop.notes}`)
  assert.deepEqual(existing, before)
  assert.equal(ticketSelections([spread], { legs: [{ ...manual, selection: '' }], notes: '' }).legs.length, 2)
})

test('duplicate contracts are rejected, including opposite sides, without changing the draft', () => {
  const existing = { legs: [spread.leg], notes: 'Keep these notes' }
  const before = structuredClone(existing)
  assert.throws(() => ticketSelections([prop, { ...spread, leg: { ...spread.leg, selection: 'Yes' } }], existing), /already on this ticket/)
  assert.deepEqual(existing, before)
  assert.throws(() => ticketSelections([spread, spread]), /already on this ticket/)
})

test('notes and leg limits reject the whole transfer instead of truncating data', () => {
  assert.equal(ticketSelections([{ ...spread, notes: 'n'.repeat(10000) }]).notes.length, 10000)
  assert.throws(() => ticketSelections([{ ...spread, notes: 'n'.repeat(10000) }, prop]), /10,000/)
  assert.throws(() => ticketSelections([prop], { legs: [spread.leg], notes: 'n'.repeat(10000) }), /10,000/)
  const picks = Array.from({ length: 100 }, (_, i) => ({ leg: { ...spread.leg, market_ticker: `MARKET-${i}` } }))
  assert.equal(ticketSelections(picks).legs.length, 100)
  assert.throws(() => ticketSelections([...picks, prop]), /100 legs/)
})

test('college picks retain exact IDs and notes in single and mixed NFL/CFB tickets', () => {
  const college = { leg: { description: 'BYU vs UCF · BYU −7.5', selection: 'No', market_ticker: 'KXNCAAFSPREAD-26OCT24BYUUCF-BYU8', game_id: '401868100' }, notes: 'Opponent strength matters.' }
  assert.deepEqual(ticketSelections([college]), { kind: 'single', legs: [college.leg], notes: college.notes })
  const mixed = ticketSelections([spread, college])
  assert.equal(mixed.kind, 'combo')
  assert.deepEqual(mixed.legs, [spread.leg, college.leg])
  assert.ok(mixed.notes.includes(college.notes))
  assert.throws(() => ticketSelections([college, college]), /already on this ticket/)
})
