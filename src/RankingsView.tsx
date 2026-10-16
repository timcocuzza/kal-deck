import { useState } from 'react'
import { useReport } from './useReport'
import { Dropdown, Modal } from './ui'

export type Metric = {
  value: number | null
  rank?: number | null
  incomplete: boolean
  coverage: { games_used: number; games_expected: number; samples_used: number | null; samples_expected: number | null }
}
type CategoryResult = {
  headline: Metric
  supporting: Record<string, Metric>
  opponent_current_rank?: number | null
  opponent_rank_incomplete?: boolean
}
type Game = {
  game_id: string; week: number; date: string; opponent: string; home: boolean
  categories: Record<string, CategoryResult>; blitz: Metric
}
export type RankedTeam = {
  team: string; games_played: number; categories: Record<string, CategoryResult>
  blitz: Metric; games: Game[]
}
export type LeagueSummary = {
  mean: number | null; median: number | null
  teams_used: number; teams_expected: number; incomplete: boolean
}
export type RankingReport = {
  season: number; completed_games: number; teams: RankedTeam[]; warnings: string[]
  categories: { key: string; label: string; measure: string; higher_is_better: boolean }[]
  sources: { name: string; label: string; fetched_at: string | null; error: string | null }[]
  league?: { categories: Record<string, LeagueSummary>; blitz: LeagueSummary }
}

function format(value: number | null) {
  return value === null ? 'Unavailable' : value.toLocaleString(undefined, { maximumFractionDigits: 3 })
}

export function LeagueContext({ summary, percent = false }: { summary?: LeagueSummary; percent?: boolean }) {
  const display = (value: number | null | undefined) => `${format(value ?? null)}${percent && value != null ? '%' : ''}`
  return <small className="league-context" title={summary
    ? `Each team’s season value is weighted equally. ${summary.teams_used}/${summary.teams_expected} teams have values. Unavailable values are excluded; incomplete team data is flagged.`
    : 'League comparison is unavailable.'}>
    · League mean {display(summary?.mean)} · Median {display(summary?.median)}
    {summary?.incomplete && <span> · Incomplete ({summary.teams_used}/{summary.teams_expected} teams; missing values or incomplete team data)</span>}
  </small>
}

export function coverage(metric: Metric) {
  const c = metric.coverage
  return `${c.games_used}/${c.games_expected} games${c.samples_used === null ? '' : ` · ${c.samples_used}/${c.samples_expected} eligible plays with data`}`
}

export function MetricValue({ metric, percent = false }: { metric: Metric | undefined; percent?: boolean }) {
  if (!metric) return <span>Unavailable</span>
  return <span title={coverage(metric)}>
    {format(metric.value)}{percent && metric.value !== null ? '%' : ''}
    {metric.incomplete && <small className="metric-note">Incomplete · {coverage(metric)}</small>}
  </span>
}

export function statLabel(key: string, category: string, game = false) {
  const allowed = category.endsWith('_defense') ? ' allowed' : ''
  const labels: Record<string, string> = {
    yards_per_game: `Yards${allowed}${game ? '' : ' / game'}`,
    yards_per_attempt: `Yards${allowed} / attempt`,
    yards_per_carry: `Yards${allowed} / carry`,
    completion_percentage: `Completion percentage${allowed}`,
    touchdowns: `Touchdowns${allowed}`,
    interceptions: 'Interceptions',
    success_percentage: `Rushing success${allowed}`,
    opponent_sacks_allowed_per_game: `${game ? 'Opponent’s' : 'Opponents’ average'} sacks allowed / game`,
    opponent_sacks_per_game: `${game ? 'Opponent’s' : 'Opponents’ average'} sacks / game`,
  }
  return labels[key] ?? key
}

export const opposing: Record<string, string> = {
  passing_offense: 'passing_defense', passing_defense: 'passing_offense',
  rushing_offense: 'rushing_defense', rushing_defense: 'rushing_offense',
  pass_protection: 'pass_rush', pass_rush: 'pass_protection', blitz: 'blitz',
}

export function RankingSources({ report }: { report: RankingReport }) {
  return <details className="provenance"><summary>Ranking sources & coverage{report.warnings.length ? ` (${report.warnings.length})` : ''}</summary>
    <p>Regular season including overtime. EPA, rushing success and blitz rates weight each game equally. Exact ties share ranks; displayed values are rounded.</p>
    <ul>{report.sources.map(source => <li key={source.name}>{source.label}: {source.fetched_at ? new Date(source.fetched_at).toLocaleString() : 'Not downloaded'}
      {source.error && ` · Refresh failed: ${source.error}. Saved data may be out of date.`}</li>)}</ul>
    <p>Coverage uses completed games in the saved schedule. Independently refreshed sources may have different update times.</p>
    {report.warnings.map(warning => <p key={warning}>{warning}</p>)}
  </details>
}

export function TeamLog({ team, category, report }: { team: RankedTeam; category: string; report: RankingReport }) {
  const blitz = category === 'blitz'
  const definition = report.categories.find(item => item.key === category)
  const value = blitz ? team.blitz : team.categories[category]?.headline
  const columns = Object.keys(team.categories[category]?.supporting ?? {})
  if (!value) return <p>This category is unavailable in the saved data.</p>
  return <section className="team-log">
    <div className="log-context"><span><strong>{value.rank == null ? 'Unranked' : `#${value.rank}`}</strong> · <MetricValue metric={value} percent={blitz} /> {blitz ? 'FTN-charted blitz rate' : definition?.measure}</span>
      <small>{coverage(value)} · {blitz ? 'Most frequent first' : definition?.higher_is_better ? 'Higher is better' : 'Lower is better'}</small></div>
    <LeagueContext summary={blitz ? report.league?.blitz : report.league?.categories[category]} percent={blitz} />
    <p className="source-note">{blitz ? 'At least one FTN-charted blitzer on an eligible dropback. Frequency is not effectiveness.' : 'Opponent ranks and sack averages use their current season results, including head-to-head games.'}</p>
    <div className="table-scroll" tabIndex={0}><table>
      <caption>{team.team} · {blitz ? 'FTN-charted blitz rate' : definition?.label} · {report.season}</caption>
      <thead><tr><th>Week / date</th><th>Opponent</th>{!blitz && <th>Opponent current {report.categories.find(item => item.key === opposing[category])?.label.toLowerCase()} rank</th>}
        <th>{blitz ? 'Blitz rate' : category === 'pass_rush' ? 'Sacks' : category === 'pass_protection' ? 'Sacks allowed' : definition?.measure}</th>
        {columns.map(key => <th key={key}>{statLabel(key, category, true)}</th>)}</tr></thead>
      <tbody>{[...team.games].reverse().map(game => <tr key={game.game_id}>
        <td>{game.week}<small className="metric-note">{game.date}</small></td><td>{game.home ? 'vs' : 'at'} {game.opponent}</td>
        {!blitz && <td>{game.categories[category]?.opponent_current_rank == null ? 'Unranked' : `#${game.categories[category].opponent_current_rank}`}
          {game.categories[category]?.opponent_rank_incomplete && <small className="metric-note">Incomplete</small>}</td>}
        <td><MetricValue metric={blitz ? game.blitz : game.categories[category]?.headline} percent={blitz} /></td>
        {columns.map(key => <td key={key}><MetricValue metric={game.categories[category]?.supporting[key]} percent={key.endsWith('percentage')} /></td>)}
      </tr>)}</tbody>
    </table></div>
    {!team.games.length && <p>No verified completed games.</p>}
    <RankingSources report={report} />
  </section>
}

export function RankingInspection({ season, revision, teamCode, category }: { season: string; revision: number; teamCode: string; category: string }) {
  const { data, error, loading } = useReport<RankingReport>(`/api/rankings?season=${season}`, revision)
  const team = data?.teams.find(team => team.team === teamCode)
  return <>{loading && !data && <p role="status">Loading team history…</p>}{error && <p role="alert">{error}</p>}
    {data && team && <TeamLog team={team} category={category} report={data} />}
    {!loading && !team && <p>No saved team statistics for this selection.</p>}</>
}

export function RankingsView({ season, revision, refreshing, teamCodes, initialCategory, categoryKeys }: {
  season: string; revision: number; refreshing: boolean; teamCodes?: string[]; initialCategory?: string; categoryKeys?: string[]
}) {
  const { data: report, error, loading } = useReport<RankingReport>(`/api/rankings?season=${season}`, revision)
  const [selected, setSelected] = useState('')
  const [open, setOpen] = useState(initialCategory ?? '')
  const teams = teamCodes ? teamCodes.flatMap(code => report?.teams.filter(team => team.team === code) ?? []) : report?.teams ?? []
  const team = teams.find(team => team.team === selected) ?? teams[0]
  const categories = report?.categories.filter(category => !categoryKeys || categoryKeys.includes(category.key)) ?? []
  return <section className="rankings">
    <div className="section-heading"><h2>Team rankings</h2>{team && <Dropdown label="Team" value={team.team} onChange={value => { setSelected(value); setOpen('') }} options={teams.map(team => ({ value: team.team, label: team.team }))} />}</div>
    {loading && !report && <p role="status">Calculating saved rankings…</p>}{error && <p role="alert">{error}</p>}
    {refreshing && <p className="source-note" role="status">Refreshing sources · Saved rankings remain visible.</p>}
    {report && <RankingSources report={report} />}
    {report?.sources.some(source => source.error) && <p role="status">A ranking source refresh failed. Check saved-data timestamps.</p>}
    {team && report && <><div className="ranking-cards">
      {categories.map(category => {
        const data = team.categories[category.key]
        return <article key={category.key} className="ranking-card"><h3>{category.label}</h3>
          <button className="rank-button" onClick={() => setOpen(category.key)} aria-label={`Open ${team.team} ${category.label} game log`}>
            {data.headline.rank == null ? 'Unranked' : `#${data.headline.rank}`} <small>Game log ↗</small></button>
          <p><MetricValue metric={data.headline} /> {category.measure}</p>
          <LeagueContext summary={report.league?.categories[category.key]} />
          <small className="metric-note">{category.higher_is_better ? 'Higher' : 'Lower'} is better · {coverage(data.headline)}</small>
          <details className="support-details"><summary>Supporting stats</summary><dl className="supporting-stats">{Object.entries(data.supporting).map(([key, value]) => <div key={key}>
            <dt>{statLabel(key, category.key)}</dt><dd><MetricValue metric={value} percent={key.endsWith('percentage')} /></dd></div>)}</dl></details>
        </article>
      })}
      {!categoryKeys && <article className="ranking-card"><h3>FTN-charted blitz rate</h3>
        <button className="rank-button" onClick={() => setOpen('blitz')}>{team.blitz.rank == null ? 'Unranked' : `#${team.blitz.rank}`} <small>Game log ↗</small></button>
        <p><MetricValue metric={team.blitz} percent /></p><LeagueContext summary={report.league?.blitz} percent />
        <small className="metric-note">#1 means most frequent · {coverage(team.blitz)}</small>
        <p className="source-note">Frequency, not defensive effectiveness.</p></article>}
    </div>{open && <Modal title={`${team.team} · ${open === 'blitz' ? 'FTN-charted blitz rate' : report.categories.find(category => category.key === open)?.label ?? open}`} onClose={() => setOpen('')}>
      <TeamLog team={team} category={open} report={report} /></Modal>}</>}
  </section>
}
