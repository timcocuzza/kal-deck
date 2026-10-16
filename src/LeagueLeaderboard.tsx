import type { ReactNode } from 'react'
import { useId } from 'react'
import { Modal } from './ui'
import { teamStyle } from './teamColors'
import { orderedLeaderboard } from './leaderboardOrder'

export type LeaderboardRow = {
  team: string; rank?: number | null; value: ReactNode; supporting: ReactNode
}

export function LeagueLeaderboard({ title, season, measure, rows, note, children, onClose }: {
  title: string; season: string; measure: string; rows: LeaderboardRow[]; note: string
  children?: ReactNode; onClose: () => void
}) {
  const id = useId()
  return <Modal title={`${title} · League leaderboard`} closeLabel="Close leaderboard" onClose={onClose} className="leaderboard-dialog">
    <p className="source-note">{season} · {rows.length} teams · {note}</p>
    <p className="source-note">Expand a team for supporting stats. Tied teams share ranks; unavailable teams appear last.</p>
    <div className="leaderboard-heading" aria-hidden="true"><span>Rank</span><span>Team</span><span>{measure}</span><span>Stats</span></div>
    <ol className="league-leaderboard" aria-label={`${title} league standings`}>
      {orderedLeaderboard(rows).map(row => <li key={row.team} style={teamStyle(row.team)}>
        <details className="leaderboard-team">
          <summary aria-label={`${row.team} · ${row.rank == null ? 'Unranked' : `Rank ${row.rank}`} · Supporting stats`} aria-describedby={`${id}-${row.team}-value`}>
            <span className="leaderboard-rank">{row.rank == null ? '—' : `#${row.rank}`}</span>
            <strong className="leaderboard-name">{row.team}</strong>
            <span className="leaderboard-value" id={`${id}-${row.team}-value`}>{row.value}</span>
          </summary>
          <div className="leaderboard-support">{row.supporting}</div>
        </details>
      </li>)}
    </ol>
    {!rows.length && <p>No league data is available for this season.</p>}
    {children}
  </Modal>
}
