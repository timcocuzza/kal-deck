export type EloGame = {
  game_id: string; season: number; kickoff: string; week: string; phase: string
  home_team: string; away_team: string; neutral: boolean
  home_score: number | null; away_score: number | null
  status: 'completed' | 'upcoming' | 'awaiting_score'
  basis: 'pregame_ratings' | 'latest_ratings'
  home_expected_score: number; away_expected_score: number; home_advantage: number
}
export type EloLog = Omit<EloGame, 'status' | 'basis'> & {
  opponent: string; side: 'home' | 'away'; rating_before: number; rating_after: number
  change: number; expected_score: number; result: number
}
export type EloTeam = {
  team: string; rating: number; rank: number; season_start_rating: number
  season_change: number; last_change: number | null; games_played: number; games: EloLog[]
}
export type EloData = {
  season: number; available: boolean; teams: EloTeam[]; matchups: EloGame[]; warnings: string[]
  league?: { mean: number; median: number; direction: string; teams: number }
  latest_result_kickoff?: string | null; replayed_games?: number
  sources: { status: string; fetched_at: string | null; source_updated_at: string | null
    attempted_at: string | null; error: string | null; url?: string; warnings?: string[] }[]
}
export class EloError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}
export async function readElo(season: string, signal: AbortSignal): Promise<EloData> {
  const response = await fetch(`/api/elo?season=${encodeURIComponent(season)}`, { signal })
  const data = await response.json()
  if (!response.ok) throw new EloError(typeof data.detail === 'string' ? data.detail : `Elo unavailable (HTTP ${response.status}).`, response.status)
  if (data.season !== Number(season) || typeof data.available !== 'boolean'
    || !Array.isArray(data.teams) || !Array.isArray(data.matchups)) throw new EloError('Elo response does not match the selected season.', 422)
  return data as EloData
}
export function eloMatchup(data: EloData | null, game: {
  game_id: string; home: { code: string }; away: { code: string }; neutral: boolean
}) {
  if (!data?.available) return undefined
  return data.matchups.find(row => row.game_id === game.game_id && row.season === data.season
    && row.home_team === game.home.code && row.away_team === game.away.code && row.neutral === game.neutral)
}
