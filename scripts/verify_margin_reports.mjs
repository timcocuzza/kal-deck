// Read-only verification against the normal running application; no mock server.
// node --experimental-strip-types scripts/verify_margin_reports.mjs OUTPUT BASE_URL SEASON nfl:8 cfb:9 ...
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { assessMarginForecast, contractDifference, MAX_SOURCE_AGE_MS } from '../src/margins.ts'
const [output, base, season, ...requests] = process.argv.slice(2)
if (!output || !base || !season || !requests.length) throw Error('Supply OUTPUT BASE_URL SEASON sport:week ...')
const audit = { captured_at: new Date().toISOString(), origin: base, season: Number(season),
  evidence: 'Real application HTTP responses. Aging checks below advance only the verifier clock, not source timestamps or application data.', reports: [] }
for (const request of requests) {
  const [sport, week] = request.split(':')
  assert.ok(['nfl', 'cfb'].includes(sport) && /^\d+$/.test(week))
  const path = `/api/${sport === 'cfb' ? 'cfb/' : ''}matchups?season=${season}&week=${week}`
  const response = await fetch(new URL(path, base))
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('cache-control'), 'no-store')
  const raw = await response.text(), report = JSON.parse(raw), now = Date.now()
  const record = { path, response_sha256: createHash('sha256').update(raw).digest('hex'),
    captured_at: new Date(now).toISOString(), sources: report.sources, games: [],
    checks: { available: 0, unavailable: 0, neutral: 0, home_contracts: 0, away_contracts: 0, aging_boundaries: 0 } }
  for (const game of report.games) {
    const f = game.margin_forecast
    assert.equal(f.game_id, game.game_id)
    assert.equal(f.season, Number(season))
    assert.equal(f.home_team_id, game.home.id ?? game.home.code)
    assert.equal(f.away_team_id, game.away.id ?? game.away.code)
    assert.equal(f.neutral, game.neutral)
    assert.equal(f.kickoff, game.kickoff)
    assert.equal(f.freshness_policy.max_source_age_hours, 24)
    const effective = assessMarginForecast(f, now)
    const comparisons = []
    if (f.available) {
      record.checks.available++
      assert.equal(effective.available, true, 'Available server forecast must still have timestamp-valid inputs')
      assert.ok(Date.parse(f.kickoff) > now)
      assert.ok(Number.isFinite(f.home_margin))
      assert.ok(Date.parse(f.training_cutoff) < Date.parse(f.ratings_as_of))
      assert.ok(f.source_freshness.length >= 2)
      if (sport === 'cfb') assert.ok(game.home.is_fbs && game.away.is_fbs)
      if (game.neutral) record.checks.neutral++
      const expiry = Math.min(...f.source_freshness.map(s => Date.parse(s.fetched_at))) + MAX_SOURCE_AGE_MS
      assert.equal(assessMarginForecast(f, expiry).available, true)
      assert.equal(assessMarginForecast(f, expiry + 1).available, false)
      assert.equal(assessMarginForecast(f, expiry + 1).home_margin, null)
      assert.equal(assessMarginForecast(f, expiry + 1).prediction_as_of, f.prediction_as_of)
      record.checks.aging_boundaries++
      for (const market of game.markets) {
        assert.equal(market.operator, 'gt'); assert.equal(market.no_push, true)
        assert.equal(market.threshold % 1, 0.5)
        const side = market.team_id === f.home_team_id ? 'home' : market.team_id === f.away_team_id ? 'away' : null
        assert.ok(side, 'Contract must join a verified participant')
        const gap = contractDifference(f, market, now)
        assert.equal(gap, (side === 'home' ? 1 : -1) * f.home_margin - market.threshold)
        assert.equal(contractDifference(f, market, expiry + 1), null)
        record.checks[`${side}_contracts`]++
        // Keep one real contract per side, plus the default selection, for review.
        if (!comparisons.some(c => c.side === side) || market.ticker === game.default_market_ticker)
          comparisons.push({ side, ticker: market.ticker, team_id: market.team_id, threshold: market.threshold,
            operator: market.operator, no_push: market.no_push, difference: gap, rules: market.rules })
      }
    } else {
      record.checks.unavailable++
      assert.equal(f.home_margin, null)
      assert.ok(f.unavailable_reason)
      for (const market of game.markets) assert.equal(contractDifference(f, market, now), null)
    }
    record.games.push({ game_id: game.game_id, home: game.home.name, away: game.away.name,
      home_is_fbs: game.home.is_fbs, away_is_fbs: game.away.is_fbs,
      venue: game.venue ?? game.stadium, forecast: f, comparisons })
  }
  audit.reports.push(record)
  console.log(request, JSON.stringify(record.checks))
}
await writeFile(output, JSON.stringify(audit, null, 2) + '\n')
