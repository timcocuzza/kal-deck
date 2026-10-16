import { useEffect, useState } from 'react'
import { teamStyle } from './teamColors'
import { Modal } from './ui'
import { EloError, eloMatchup, readElo } from './elo'
import type { EloData, EloTeam } from './elo'

const number = (value: number) => value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const change = (value: number) => `${value > 0 ? '+' : ''}${number(value)}`
const percent = (value: number) => `${number(value * 100)}%`
const date = (value?: string | null) => value ? new Date(value).toLocaleString() : 'Not supplied'

export function useElo(season: string, revision: number) {
  const [snapshot, setSnapshot] = useState<EloData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    setError(''); setLoading(true)
    const timeout = window.setTimeout(() => controller.abort(), 30000)
    void readElo(season, controller.signal)
      .then(data => { if (!disposed) setSnapshot(data) })
      .catch((cause: unknown) => {
        if (disposed) return
        if (cause instanceof EloError && cause.status === 422) setSnapshot(null)
        setError(cause instanceof Error ? cause.message : 'Elo unavailable.')
      })
      .finally(() => { window.clearTimeout(timeout); if (!disposed) setLoading(false) })
    return () => { disposed = true; controller.abort(); window.clearTimeout(timeout) }
  }, [season, revision])
  return { data: snapshot?.season === Number(season) ? snapshot : null, error, loading }
}

export function EloSources({ data, error, loading }: ReturnType<typeof useElo>) {
  return <details className="provenance elo-provenance">
    <summary>Elo · {loading ? 'Loading saved ratings…' : error || data?.sources.some(s => s.status === 'refresh_failed')
      ? 'Needs attention' : data?.available ? 'Saved ratings' : 'Unavailable'}</summary>
    {error && <p role="alert">{error}{data?.available ? ' Showing previously loaded ratings.' : ''}</p>}
    {!loading && !data?.available && <p>Refresh <strong>Elo game history</strong> under Data sources. Elo supports seasons 2002–2100.</p>}
    <p>Elo expected score = P(win) + ½ P(tie). It is not a spread-cover probability or a Kalshi price.</p>
    <p>Future matchups use the latest ratings, without simulating intervening games.</p>
    {data?.league && <p>League mean {number(data.league.mean)} · median {number(data.league.median)} · {data.league.teams} teams · Higher is better.</p>}
    {data?.available && <p>{data.replayed_games?.toLocaleString()} games replayed since 2002, including playoffs.
      {' '}Latest included result’s kickoff: {date(data.latest_result_kickoff)}.</p>}
    {data?.warnings.map(warning => <p key={warning}>{warning}</p>)}
    {data?.sources.map((source, index) => <div key={index}>
      <p>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">Elo game history · nflverse</a> : 'Elo game history'}
        {' · Fetched: '}{date(source.fetched_at)}{' · Source update: '}{date(source.source_updated_at)}</p>
      {source.error && <p role="alert">Refresh failed: {source.error} · Attempted: {date(source.attempted_at)}. Saved results retained where available.</p>}
      {source.warnings?.map(warning => <p key={warning}>{warning}</p>)}
    </div>)}
  </details>
}

export function EloCard({ data, game, onTeam }: {
  data: EloData | null
  game: { game_id: string; away: { code: string }; home: { code: string }; neutral: boolean }
  onTeam: (team: EloTeam) => void
}) {
  const matchup = eloMatchup(data, game)
  return <section className="elo-card" aria-label="Elo ratings">
    <div className="elo-columns">{(['away', 'home'] as const).map(side => {
      const code = game[side].code
      const team = data?.available ? data.teams.find(t => t.team === code) : undefined
      return team ? <button key={side} className="elo-team" style={teamStyle(code)} onClick={() => onTeam(team)} aria-label={`Open ${code} Elo game history`}>
        <span>{code} <small>#{team.rank}</small></span>
        <strong>{number(team.rating)}</strong>
        {matchup && <span>{percent(matchup[`${side}_expected_score`])}</span>}
        <small>Last game {team.last_change === null ? '—' : change(team.last_change)}</small>
      </button> : <div key={side} className="elo-team" style={teamStyle(code)}>{code}<small>Rating unavailable</small></div>
    })}</div>
    {matchup?.status === 'awaiting_score' && <small>Awaiting published score · Latest ratings</small>}
    {matchup?.basis === 'pregame_ratings' && <small>Expected score uses pregame ratings; team ratings are current.</small>}
  </section>
}

export function EloTeamDialog({ team, season, onClose }: { team: EloTeam; season: string; onClose: () => void }) {
  return <Modal title={`${team.team} · Elo game history`} onClose={onClose}>
    <p>#{team.rank} · {number(team.rating)} Elo · {change(team.season_change)} this season</p>
    <p className="source-note">{season} regular season and playoffs · {team.games_played} completed games · Season opening {number(team.season_start_rating)}</p>
    <div className="table-scroll"><table>
      <thead><tr><th>Week</th><th>Opponent</th><th>Result</th><th>Before</th><th>Elo expected score</th><th>Change</th><th>After</th></tr></thead>
      <tbody>{[...team.games].reverse().map(game => <tr key={game.game_id}>
        <td>{game.phase} {game.week}<small className="metric-note">{date(game.kickoff)}</small></td>
        <td>{game.neutral ? 'vs' : game.side === 'away' ? 'at' : 'vs'} {game.opponent}</td>
        <td>{game.result === 1 ? 'W' : game.result === 0 ? 'L' : 'T'} {game[`${game.side}_score`]}–{game[game.side === 'home' ? 'away_score' : 'home_score']}</td>
        <td>{number(game.rating_before)}</td><td>{percent(game.expected_score)}</td>
        <td>{change(game.change)}</td><td>{number(game.rating_after)}</td>
      </tr>)}</tbody>
    </table></div>
    {!team.games.length && <p>No completed games in the selected season.</p>}
    <p className="source-note">Elo expected score includes half the probability of a tie. Completion uses past kickoff plus published scores; nflverse supplies no explicit final status.</p>
  </Modal>
}
