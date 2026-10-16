import { useState } from 'react'
import { EloSources, EloTeamDialog, useElo } from './EloView'
import type { EloTeam } from './elo'
import { LeagueLeaderboard } from './LeagueLeaderboard'

const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })
const change = (value: number) => `${value > 0 ? '+' : ''}${number(value)}`

function EloSupportingStats({ team }: { team: EloTeam }) {
  const wins = team.games.filter(game => game.result === 1).length
  const losses = team.games.filter(game => game.result === 0).length
  const ties = team.games.filter(game => game.result === .5).length
  return <dl className="supporting-stats">
    <div><dt>Season opening Elo</dt><dd>{number(team.season_start_rating)}</dd></div>
    <div><dt>Season change</dt><dd>{change(team.season_change)}</dd></div>
    <div><dt>Last game change</dt><dd>{team.last_change == null ? 'No completed games' : change(team.last_change)}</dd></div>
    <div><dt>Completed games</dt><dd>{team.games_played}</dd></div>
    <div><dt>Record (W–L–T)</dt><dd>{wins}–{losses}–{ties}</dd></div>
  </dl>
}

export function EloRankingCard({ season, revision, teamCode }: { season: string; revision: number; teamCode?: string }) {
  const result = useElo(season, revision)
  const { data, error, loading } = result
  const [board, setBoard] = useState(false)
  const [history, setHistory] = useState(false)
  const team = data?.available ? data.teams.find(item => item.team === teamCode) : undefined
  return <article className="ranking-card"><h3>Elo rating</h3>
    {team ? <>
      <button className="rank-button" onClick={() => setHistory(true)} aria-label={`Open ${team.team} Elo game history`}>#{team.rank} <small>Game log ↗</small></button>
      <p>{number(team.rating)} Elo</p>
      <small className="metric-note">Higher is better · Regular season and playoffs</small>
    </> : <p role="status">{loading ? 'Loading Elo…' : data?.available ? 'No Elo rating for this team.' : 'Elo unavailable. Refresh Elo game history under Data.'}</p>}
    {error && <p role="alert">{error}</p>}
    <button className="leaderboard-open" disabled={!data?.available} onClick={() => setBoard(true)} aria-label="View Elo league leaderboard">League leaderboard ↗</button>
    <EloSources {...result} />
    {team && <details className="support-details"><summary>Supporting stats</summary><EloSupportingStats team={team} /></details>}
    {history && team && <EloTeamDialog team={team} season={season} onClose={() => setHistory(false)} />}
    {board && data?.available && <LeagueLeaderboard title="Elo rating" season={season} measure="Elo" onClose={() => setBoard(false)}
      note="Higher is better. Ratings include regular season and playoffs."
      rows={data.teams.map(item => ({ team: item.team, rank: item.rank, value: number(item.rating), supporting: <EloSupportingStats team={item} /> }))}>
      <EloSources {...result} />
    </LeagueLeaderboard>}
  </article>
}
