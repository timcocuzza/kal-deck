import { useId, useState } from 'react'
import { DataNotices } from './DataNotices'
import type { ReactNode } from 'react'
import { useReport } from './useReport'
import { Modal } from './ui'
import { LeagueContext, MetricValue } from './RankingsView'
import type { LeagueSummary, Metric } from './RankingsView'

type Category = { headline: Metric; supporting: Record<string, Metric> }
export type PositionReport = {
  season: number; completed_games: number; warnings: string[]
  categories: { key: string; label: string; measure: string }[]
  league: Record<string, LeagueSummary>
  teams: { team: string; games_played: number; categories: Record<string, Category>
    games: { game_id: string; week: number; date: string; opponent: string; home: boolean; categories: Record<string, Category>; notes: string[] }[] }[]
  sources: { name: string; label: string; fetched_at: string | null; error: string | null }[]
}
function statLabel(key: string, game = false) {
  const suffix = game ? '' : ' / game'
  const labels: Record<string, string> = {
    targets_per_game: `Targets${suffix}`, targets: 'Total targets', receptions_per_game: `Receptions${suffix}`,
    carries_per_game: `Carries${suffix}`, carries: 'Total carries',
    yards_per_target: 'Yards / target', yards_per_carry: 'Yards / carry', touchdowns: 'Touchdowns allowed',
    designed_yards_per_game: `QB designed-run yards${suffix}`, scramble_yards_per_game: `QB scramble yards${suffix}`,
    kneel_yards_per_game: `QB kneeldown yards${suffix}`,
  }
  return labels[key] ?? key
}

function PositionLogContainer({ embedded, title, children, onClose }: { embedded: boolean; title: string; children: ReactNode; onClose: () => void }) {
  return embedded ? <section aria-label={title}>{children}</section> : <Modal title={title} onClose={onClose}>{children}</Modal>
}

export function PositionDefenseView({ season, revision, refreshing, teamCodes, categoryKeys, initialCategory, embedded = false }: {
  season: string; revision: number; refreshing: boolean; teamCodes?: string[]; categoryKeys?: string[]; initialCategory?: string; embedded?: boolean
}) {
  const { data: report, error, loading } = useReport<PositionReport>(`/api/position-defense?season=${season}`, revision)
  const [selected, setSelected] = useState('')
  const [open, setOpen] = useState(initialCategory ?? '')
  const id = useId()
  const teams = report?.teams.filter(team => !teamCodes || teamCodes.includes(team.team)) ?? []
  const team = teams.find(item => item.team === selected) ?? teams[0]
  const categories = report?.categories.filter(category => !categoryKeys || categoryKeys.includes(category.key)) ?? []
  return <section className="rankings position-defense" aria-labelledby={`${id}-title`}>
    <h3 id={`${id}-title`}>Defense by opponent position</h3>
    <p className="source-note">Current regular season, including overtime. #1 allows the fewest yards per team game.
      These are totals against the entire position group, not a prediction for one player. No opponent-strength adjustment. Exact ties share ranks; displayed values are rounded.</p>
    {loading && <p role="status">Calculating position-specific defense from saved data…</p>}
    {refreshing && <p role="status">Sources are refreshing; rankings update when the refresh finishes.</p>}
    {error && <p role="alert">{error}</p>}
    {report && <details className="provenance"><summary>Sources and coverage notices ({report.warnings.length})</summary>
      <ul>{report.sources.map(source => <li key={source.name}>{source.label}: {source.fetched_at ? new Date(source.fetched_at).toLocaleString() : 'Not downloaded'}
        {source.error && ` · Refresh failed: ${source.error}. Saved data may be out of date.`}</li>)}</ul>
      <p>All completed games in the saved schedule count equally, including verified zeroes. Unverifiable games are excluded and flagged. No minimum sample cutoff. Positions use each game's player statistics.</p>
      <DataNotices warnings={report.warnings} />
    </details>}
    {report?.sources.some(source => source.error) && <p role="status">A source refresh failed. Check timestamps before using these saved rankings.</p>}
    {team && report && <>
      <label htmlFor={`${id}-team`}>Defense </label>
      <select id={`${id}-team`} value={team.team} onChange={event => { setSelected(event.target.value); setOpen('') }}>
        {teams.map(item => <option key={item.team} value={item.team}>{item.team}</option>)}
      </select>
      <p className="source-note">{team.games_played} completed games. Opportunity totals and ratios use available verified games; zero opportunities give an unavailable ratio.</p>
      {categories.map(category => {
        const data = team.categories[category.key]
        const columns = Object.keys(data.supporting)
        return <article key={category.key}>
          <h4>{team.team} · {category.label}</h4>
          <button aria-expanded={open === category.key} aria-controls={`${id}-${category.key}`}
            onClick={() => setOpen(open === category.key ? '' : category.key)}>
            {data.headline.rank == null ? 'Unranked' : `#${data.headline.rank}`} · {open === category.key ? 'Hide' : 'View'} game log
          </button>
          <p><MetricValue metric={data.headline} /> yards allowed / game · Lower is better
            <LeagueContext summary={report.league[category.key]} /></p>
          <p className="source-note">Coverage: {data.headline.coverage.games_used}/{data.headline.coverage.games_expected} games.</p>
          <dl className="supporting-stats">{columns.map(key => <div key={key}><dt>{statLabel(key)}</dt><dd><MetricValue metric={data.supporting[key]} /></dd></div>)}</dl>
          {category.key === 'qb_rushing' && <p className="source-note">Official totals include designed runs, scrambles and kneeldowns. A breakdown is shown only when every QB's rushing yards and carries reconcile with play-by-play. Component averages may cover fewer games; inspect incomplete labels.</p>}
          {open === category.key && <PositionLogContainer embedded={embedded} title={`${team.team} · ${category.label}`} onClose={() => setOpen('')}>
            <div id={`${id}-${category.key}`}>
            <div className="table-scroll" tabIndex={0} aria-label={`${category.label} game log`}><table>
              <caption>{team.team} · {category.label}</caption>
              <thead><tr><th>Week / date</th><th>Opponent</th><th>Yards allowed</th>{columns.map(key => <th key={key}>{statLabel(key, true)}</th>)}</tr></thead>
              <tbody>{team.games.map(game => <tr key={game.game_id}>
                <td>{game.week}<small className="metric-note">{game.date}</small></td><td>{game.home ? 'vs' : '@'} {game.opponent}
                  {category.key === 'qb_rushing' && game.notes.map(note => <small className="metric-note" key={note}>{note}</small>)}</td>
                <td><MetricValue metric={game.categories[category.key].headline} /></td>
                {columns.map(key => <td key={key}><MetricValue metric={game.categories[category.key].supporting[key]} /></td>)}
              </tr>)}</tbody>
            </table></div>
            {!team.games.length && <p>No completed games.</p>}
            </div>
          </PositionLogContainer>}
        </article>
      })}
      {!categories.length && <p>No approved position-specific category applies to this selection.</p>}
    </>}
    {!loading && report && !team && <p>No team schedule is available for this selection.</p>}
  </section>
}
