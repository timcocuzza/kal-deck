import { useState } from 'react'
import { useReport } from './useReport'
import { teamStyle } from './teamColors'
import { Modal } from './ui'
import { coverage, LeagueContext, MetricValue, opposing, RankingSources, statLabel, TeamLog } from './RankingsView'
import type { RankingReport } from './RankingsView'

export function TeamComparison({ season, revision, teams }: { season: string; revision: number; teams: [string, string] }) {
  const { data: report, error, loading } = useReport<RankingReport>(`/api/rankings?season=${season}`, revision)
  const [mode, setMode] = useState('matchup')
  const [inspection, setInspection] = useState<{ team: string; category: string } | null>(null)
  const pair = teams.map(code => report?.teams.find(team => team.team === code))
  const logTeam = report?.teams.find(team => team.team === inspection?.team)
  return <section className="team-comparison">
    <div className="section-heading"><h2>Team comparison</h2><div className="segmented" aria-label="Comparison mode">
      <button aria-pressed={mode === 'matchup'} onClick={() => setMode('matchup')}>Opposing units</button>
      <button aria-pressed={mode === 'same'} onClick={() => setMode('same')}>Same units</button>
    </div></div>
    {loading && !report && <p role="status">Loading saved rankings…</p>}{error && <p role="alert">{error}</p>}
    {report?.sources.some(source => source.error) && <p role="status">A ranking source refresh failed. Check timestamps below.</p>}
    {report && <><div className="comparison-grid">{[...report.categories.map(c => c.key), 'blitz'].map(key => {
      const keys = [key, mode === 'same' ? key : opposing[key]]
      const columns = pair.map((team, side) => ({ team, key: keys[side], definition: report.categories.find(c => c.key === keys[side]),
        metric: keys[side] === 'blitz' ? team?.blitz : team?.categories[keys[side]]?.headline,
        support: Object.entries(team?.categories[keys[side]]?.supporting ?? {}) }))
      return <article className="comparison-card" key={`${mode}:${key}`}>
        <div className="compare-head"><span style={teamStyle(teams[0])}>{teams[0]}</span><span style={teamStyle(teams[1])}>{teams[1]}</span></div>
        <div className="compare-columns">{columns.map((column, side) => <button className="rank-tile" style={teamStyle(teams[side])} key={side}
          disabled={!column.team} onClick={() => setInspection({ team: teams[side], category: column.key })}>
          <strong>{column.metric?.rank == null ? 'Unranked' : `#${column.metric.rank}`}</strong>
          <span>{column.key === 'blitz' ? 'FTN-charted blitz rate' : column.definition?.label}
            <small><MetricValue metric={column.metric} percent={column.key === 'blitz'} /> {column.definition?.measure}</small></span>
          <LeagueContext summary={column.key === 'blitz' ? report.league?.blitz : report.league?.categories[column.key]} percent={column.key === 'blitz'} />
          <small>{column.key === 'blitz' ? 'Most frequent first' : column.definition?.higher_is_better ? 'Higher is better' : 'Lower is better'}</small>
        </button>)}</div>
        {key === 'blitz' ? <p className="source-note card-note">Frequency, not defensive effectiveness.</p> : <details className="support-details"><summary>Supporting stats</summary>
          <div className="support-body">{Array.from({ length: Math.max(...columns.map(c => c.support.length)) }, (_, index) => <div className="support-pair" key={index}>
            {columns.map((column, side) => {
              const stat = column.support[index]
              return <dl key={side}><dt>{stat ? statLabel(stat[0], column.key) : 'Unavailable'}</dt><dd>{stat ? <MetricValue metric={stat[1]} percent={stat[0].endsWith('percentage')} /> : '—'}</dd></dl>
            })}</div>)}<div className="support-pair support-coverage">{columns.map((column, side) => <small key={side}>{teams[side]} · {column.metric ? coverage(column.metric) : 'Unavailable'}</small>)}</div></div>
        </details>}
      </article>
    })}</div><RankingSources report={report} /></>}
    {inspection && report && logTeam && <Modal title={`${inspection.team} · ${inspection.category === 'blitz' ? 'FTN-charted blitz rate' : report.categories.find(c => c.key === inspection.category)?.label}`} onClose={() => setInspection(null)}>
      <TeamLog team={logTeam} category={inspection.category} report={report} />
    </Modal>}
  </section>
}
