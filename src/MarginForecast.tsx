import { contractDifference, differenceLabel, modelLabel } from './margins'
import type { MarginContract, MarginForecast as Forecast } from './margins'

export function MarginForecast({ forecast: f, home, away, contract, compact = false }: {
  forecast?: Forecast; home: string; away: string; contract?: MarginContract; compact?: boolean
}) {
  const available = f?.available && f.home_margin != null && Number.isFinite(f.home_margin)
  const difference = contractDifference(f, contract)
  const team = contract?.team_id === f?.home_team_id ? home : away
  return <section className={`margin-forecast${compact ? ' compact' : ''}`} aria-label="Predicted margin">
    <div className="margin-heading"><span>Strength-only estimate</span>{f?.experimental && <small>Experimental</small>}</div>
    <strong>{available ? `Model: ${modelLabel(f.home_margin!, home, away)}` : 'Model unavailable'}</strong>
    {!available && <p>{f?.unavailable_reason ?? 'Forecast data has not loaded.'}</p>}
    {difference != null && contract && <div className="margin-contract" aria-live="polite">
      <p>Selected contract: {team} wins by over {contract.threshold.toFixed(1)}</p>
      <p>Difference: <b>{differenceLabel(difference)}</b></p>
    </div>}
    {available && <small>Not a cover probability, proven betting edge or expected profit.</small>}
    {!!f?.notices.length && <p className="margin-notice">{f.notices.join(' ')}</p>}
    {!compact && f && <details className="provenance"><summary>Forecast basis & freshness</summary>
      <p>Home score minus away score; neutral sites receive no home advantage. Ratings and fits freeze at the start of each UTC date, with a further 24-hour result embargo because historical final timestamps are unavailable.</p>
      <p>Kalshi contract thresholds are not sportsbook consensus lines. Verified contracts use strictly greater than the half-point threshold, with no push.</p>
      <p>Prediction as of: {f.prediction_as_of}<br />Ratings as of: {f.ratings_as_of}<br />Latest training result kickoff: {f.training_cutoff ?? 'Unavailable'}<br />Model: {f.model_version}</p>
      {f.source_freshness.map(s => <p key={s.name}>{s.name}: {s.status} · Fetched {s.fetched_at ?? 'unknown'} · Published update {s.source_updated_at ?? 'unspecified'}{s.error && ` · ${s.error}`}</p>)}
      <p>A recent download does not certify complete results. Corrections rebuild estimates from saved history; these are not archived live predictions.</p>
    </details>}
  </section>
}
