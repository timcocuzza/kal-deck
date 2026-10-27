export type MarginForecast = {
  game_id: string; season: number; home_team_id: string; away_team_id: string
  kickoff: string; neutral: boolean; available: boolean; home_margin: number | null
  model_version: string; experimental: boolean; prediction_as_of: string; ratings_as_of: string
  training_cutoff: string | null; unavailable_reason: string | null; notices: string[]
  freshness_policy?: { max_source_age_hours: number }
  source_freshness: { name: string; fetched_at: string | null; source_updated_at: string | null; status: string; error: string | null }[]
}
export type MarginContract = { team_id: string; threshold: number; operator: 'gt'; no_push: boolean }
// Old cached responses use the same 24-hour policy. Never extend it from the
// prediction timestamp, a successful HTTP read, or the latest training result.
export const MAX_SOURCE_AGE_MS = 24 * 60 * 60 * 1000
export function sourceTime(value: string | null) {
  return value && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? Date.parse(value) : NaN
}
export function assessMarginForecast(f: MarginForecast | undefined, now = Date.now()): MarginForecast | undefined {
  if (!f) return f
  const source_freshness = f.source_freshness.map(source => {
    const age = now - sourceTime(source.fetched_at)
    const status = !Number.isFinite(age) || age < 0 ? 'unknown'
      : age > MAX_SOURCE_AGE_MS ? 'stale' : source.error ? 'refresh_failed' : 'fresh'
    return { ...source, status }
  })
  const reason = !source_freshness.length || source_freshness.some(s => s.status === 'unknown')
    ? 'Source freshness is unknown. Refresh schedule and strength history.'
    : source_freshness.some(s => s.status === 'stale')
      ? 'Saved inputs are older than 24 hours. Refresh schedule and strength history.' : null
  // Preserve an existing context/identity/FCS failure; never revive a server refusal.
  return { ...f, source_freshness, ...(reason ? {
    available: false, home_margin: null, unavailable_reason: f.available ? reason : f.unavailable_reason ?? reason,
  } : {}) }
}
export function contractDifference(forecast: MarginForecast | undefined, contract: MarginContract | undefined, now = Date.now()) {
  const f = assessMarginForecast(forecast, now)
  if (!f?.available || f.home_margin == null || !Number.isFinite(f.home_margin) || !contract
    || contract.operator !== 'gt' || !contract.no_push || !Number.isFinite(contract.threshold)
    || contract.threshold <= 0 || contract.threshold % 1 !== 0.5) return null
  const sign = contract.team_id === f.home_team_id ? 1 : contract.team_id === f.away_team_id ? -1 : null
  return sign == null ? null : sign * f.home_margin - contract.threshold
}
export function modelLabel(margin: number, home: string, away: string) {
  const rounded = Math.round(Math.abs(margin) * 10) / 10
  return rounded === 0 ? 'Even matchup (0.0 points)' : `${margin > 0 ? home : away} by ${rounded.toFixed(1)}`
}

export function differenceLabel(difference: number) {
  return difference === 0 ? 'At threshold (0.0 points)' : `${Math.abs(difference).toFixed(1)} points ${difference > 0 ? 'above' : 'below'} threshold`
}

// Wake at expiry, and on resume/focus (background timers may be suspended).
// The minute heartbeat also catches wall-clock adjustments. This only rerenders
// the estimate; it does not alter report caches, kickoff filters, or fetch data.
export function watchMarginClock(f: MarginForecast | undefined, changed: () => void,
  windowEvents: EventTarget = window, documentEvents: EventTarget = document) {
  let timer: ReturnType<typeof setTimeout>
  const schedule = () => {
    clearTimeout(timer)
    const now = Date.now()
    const deadlines = (f?.source_freshness ?? []).map(s => sourceTime(s.fetched_at) + MAX_SOURCE_AGE_MS + 1)
      .filter(time => Number.isFinite(time) && time > now)
    timer = setTimeout(tick, Math.min(60_000, ...deadlines.map(time => time - now)))
  }
  const tick = () => { changed(); schedule() }
  windowEvents.addEventListener('focus', tick)
  windowEvents.addEventListener('pageshow', tick)
  documentEvents.addEventListener('visibilitychange', tick)
  schedule()
  return () => {
    clearTimeout(timer)
    windowEvents.removeEventListener('focus', tick)
    windowEvents.removeEventListener('pageshow', tick)
    documentEvents.removeEventListener('visibilitychange', tick)
  }
}
