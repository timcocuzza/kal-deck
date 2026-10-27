export type MarginForecast = {
  game_id: string; season: number; home_team_id: string; away_team_id: string
  kickoff: string; neutral: boolean; available: boolean; home_margin: number | null
  model_version: string; experimental: boolean; prediction_as_of: string; ratings_as_of: string
  training_cutoff: string | null; unavailable_reason: string | null; notices: string[]
  source_freshness: { name: string; fetched_at: string | null; source_updated_at: string | null; status: string; error: string | null }[]
}
export type MarginContract = { team_id: string; threshold: number; operator: 'gt'; no_push: boolean }
export function contractDifference(f: MarginForecast | undefined, contract: MarginContract | undefined) {
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
