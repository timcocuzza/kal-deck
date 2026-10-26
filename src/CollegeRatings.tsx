import { useState } from 'react'
import { useReport } from './useReport'
import { Dropdown, Modal, navigate } from './ui'
import { collegeTeamStyle, collegeAbbreviation } from './collegeColors'

type RecordLine = { wins: number; losses: number; ties?: number }
type Result = { game_id: string; date: string; opponent: string; opponent_is_fbs: boolean; venue: string; result: string;
  team_score: number; opponent_score: number; rating_before: number; rating_after: number; change: number;
  opponent_pregame_rank: number | null; opponent_current_rank: number | null; benchmark: number | null }
type Team = { id: string; name: string; rating: number; rank: number; season_change: number; last_change: number | null;
  record: RecordLine; fbs_record: RecordLine; vs_current_top25: RecordLine; games_rated: number; notices: string[];
  schedule_faced: number | null; schedule_faced_rank: number | null; opponents_now: number | null; opponents_now_rank: number | null;
  strongest_wins: Result[]; losses_to_lower_rated_teams: Result[]; games: Result[] }
export type CollegeStrengthReport = { available: boolean; season: number; teams?: Team[]; latest_result?: string | null;
  warnings: string[]; methodology?: string[]; awaiting_final_count?: number;
  sources: { name: string; fetched_at: string | null; error: string | null; warnings?: string[] }[] }
const number = (value: number | null) => value === null ? 'Unavailable' : value.toFixed(1)
const change = (value: number | null) => value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(1)}`
const record = (value: RecordLine) => `${value.wins}–${value.losses}${value.ties ? `–${value.ties}` : ''}`
const rank = (value: number | null) => value === null ? 'Unranked' : `#${value}`

function TeamSummary({ team }: { team: Team }) {
  return <dl className="supporting-stats cfb-summary">
    <div><dt>Strength</dt><dd>{number(team.rating)} <small>{rank(team.rank)}</small></dd></div>
    <div><dt>Record</dt><dd>{record(team.record)}<small>{record(team.fbs_record)} vs FBS</small></dd></div>
    <div><dt>Schedule faced</dt><dd>{rank(team.schedule_faced_rank)}<small>{rank(team.opponents_now_rank)} using current strength</small></dd></div>
    <div><dt>Season change</dt><dd>{change(team.season_change)}<small>{change(team.last_change)} last game</small></dd></div>
  </dl>
}

function TeamEvidence({ team, onClose }: { team: Team; onClose: () => void }) {
  const losses = [...team.games.filter(g => !g.opponent_is_fbs && g.result === 'L'), ...team.losses_to_lower_rated_teams]
  return <Modal title={`${team.name} · Strength history`} className="cfb-evidence-dialog" onClose={onClose}>
    <TeamSummary team={team} />
    {team.notices.map(notice => <p className="data-warning" key={notice}>{notice}</p>)}
    <details className="research-expand cfb-resume"><summary>Wins & losses <small>{record(team.vs_current_top25)} vs strength top 25</small></summary>
      <div className="college-evidence">
        <section><h3>Strongest opponents beaten</h3>{team.strongest_wins.length ? team.strongest_wins.map(g => <p key={g.game_id}><span>{g.opponent} <small>{rank(g.opponent_current_rank)}</small></span><small>{g.team_score}–{g.opponent_score} · {g.venue}</small></p>) : <p className="source-note">No rated FBS wins yet.</p>}</section>
        <section><h3>Losses to review</h3>{losses.length ? losses.map(g => <p key={g.game_id}><span>{g.opponent} <small>{g.opponent_is_fbs ? rank(g.opponent_current_rank) : 'FCS'}</small></span><small>{g.team_score}–{g.opponent_score} · {g.venue}</small></p>) : <p className="source-note">No losses in the rated results.</p>}</section>
      </div>
      <p className="source-note">Opponent ranks use current Deck strength. Use results and head-to-head meetings alongside strength when choosing your own top 25.</p>
    </details>
    <div className="table-scroll" tabIndex={0} role="region" aria-label={`${team.name} rating history`}><table>
      <caption>{team.games_rated} rated games · Most recent first</caption>
      <thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>Opponent rank<small className="metric-note">Then / now</small></th><th>Before</th><th>Change</th><th>After</th></tr></thead>
      <tbody>{[...team.games].reverse().map(g => <tr key={g.game_id}>
        <td>{new Date(g.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</td>
        <td>{g.venue === 'away' ? 'at' : 'vs'} {g.opponent}{g.venue === 'neutral' && <small className="metric-note">Neutral site</small>}{!g.opponent_is_fbs && <small className="metric-note">FCS</small>}</td>
        <td className="cfb-score">{g.result} {g.team_score}–{g.opponent_score}</td><td>{g.opponent_is_fbs ? `${rank(g.opponent_pregame_rank)} / ${rank(g.opponent_current_rank)}` : '—'}</td>
        <td>{number(g.rating_before)}</td><td>{change(g.change)}</td><td>{number(g.rating_after)}</td>
      </tr>)}</tbody>
    </table></div>
    {!team.games.length && <p>No completed games have been rated this season.</p>}
    <details className="provenance"><summary>About these ratings</summary>
      <p>Strength measures performance, not AP poll position. A win can lower a rating and a loss can raise it.</p>
      <p>Pregame opponent ranks are fixed before that date’s results. Current ranks include all rated results, including this meeting. FCS opponents count internally; their ratings and statistics are not displayed.</p>
      <p>Schedule faced uses opponents’ pregame strength; the current measure uses their latest strength. Both account for venue. A lower schedule rank means harder opposition.</p>
    </details>
  </Modal>
}

export function CollegeStrengthPair({ season, revision, ids }: { season: string; revision: number; ids: string[] }) {
  const { data, error } = useReport<CollegeStrengthReport>(`/api/cfb/strength?season=${season}`, revision)
  const [inspect, setInspect] = useState<string | null>(null)
  const selected = data?.teams?.find(t => t.id === inspect)
  if (error || !data?.available) return <p className="source-note">Strength {error ? 'unavailable' : 'not loaded'} · <button className="back-link" onClick={() => navigate('cfb/ratings')}>View ratings ↗</button></p>
  return <><section className="elo-card cfb-strength-card" aria-label="College strength ratings">
    <div className="elo-columns">{ids.map(id => {
      const team = data.teams?.find(t => t.id === id)
      return team ? <button key={id} className="elo-team" style={collegeTeamStyle(id)} onClick={() => setInspect(id)} aria-label={`Open ${team.name} strength and result evidence`}>
        <span>{collegeAbbreviation(id, team.name)} <small>{rank(team.rank)}</small></span><strong>{number(team.rating)}</strong>
        <span>SoS {rank(team.schedule_faced_rank)}</span><small>Last game {change(team.last_change)}</small>
      </button> : <div key={id} className="elo-team"><small>No public FBS rating</small></div>
    })}</div>
  </section>{data.sources.some(s => s.error) && <p className="data-warning">Strength refresh failed · Saved ratings retained.</p>}
    {selected && <TeamEvidence team={selected} onClose={() => setInspect(null)} />}</>
}

function RatingSources({ data }: { data: CollegeStrengthReport }) {
  const notes = [...new Set([...data.warnings, ...(data.methodology ?? []), ...data.sources.flatMap(s => s.warnings ?? [])])]
  return <details className="provenance"><summary>Sources & rating method{data.sources.some(s => s.error) ? ' · Needs attention' : ''}</summary>
    <p>Strength is measured in points. Schedule faced uses pregame opponent strength; Opponents now uses current strength. Both include FCS opponents internally and adjust for venue. Lower schedule ranks mean harder opposition.</p>
    <p>These are Deck research ranks, not AP ranks or an automatic ballot. Records against the top 25 use current Deck strength ranks.</p>
    {data.sources.map(s => <p key={s.name}>Results saved: {s.fetched_at ? new Date(s.fetched_at).toLocaleString() : 'Not downloaded'}{s.error && ` · Refresh failed: ${s.error}`}</p>)}
    {notes.map(note => <p key={note}>{note}</p>)}
    <p>The rating retains 40% of prior-season deviation from division strength, uses two points of home advantage, and updates by 20% of margin error capped at ±28.</p>
  </details>
}

export function CollegeRatings({ season, revision, onSeason }: { season: string; revision: number; onSeason: (value: string) => void }) {
  const { data, loading, error } = useReport<CollegeStrengthReport>(`/api/cfb/strength?season=${season}`, revision)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('rating')
  const [limit, setLimit] = useState('25')
  const [inspect, setInspect] = useState<string | null>(null)
  const selected = data?.teams?.find(t => t.id === inspect)
  const query = search.trim().toLowerCase()
  const teams = [...(data?.teams ?? [])].filter(t => t.name.toLowerCase().includes(query)).sort((a, b) => {
    const field = sort as 'rating' | 'schedule_faced' | 'opponents_now'
    return (b[field] ?? -Infinity) - (a[field] ?? -Infinity) || a.rank - b.rank || a.name.localeCompare(b.name)
  }).slice(0, query || limit === 'all' ? undefined : 25)
  const scheduleLabel = sort === 'opponents_now' ? 'SoS now' : 'SoS faced'
  return <section className="research-page college-ratings" aria-label="College ratings and top 25 research">
    <div className="page-heading"><div><h1>College ratings</h1><p>Strength & schedule · Build your own top 25</p></div>
      <Dropdown label="College rating season" value={season} onChange={onSeason} options={Array.from({ length: new Date().getFullYear() - 2016 }, (_, i) => String(new Date().getFullYear() - i)).map(y => ({ value: y, label: y }))} />
    </div>
    <div className="cfb-rating-toolbar">
      <label className="cfb-team-search"><span className="sr-only">Find a team</span><input type="search" placeholder="Find a team…" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <div className="controls"><Dropdown label="Order teams by" value={sort} onChange={setSort} options={[{ value: 'rating', label: 'Overall strength' }, { value: 'schedule_faced', label: 'Schedule faced' }, { value: 'opponents_now', label: 'Opponents now' }]} />
        <div className="segmented" role="group" aria-label="Teams shown"><button aria-pressed={limit === '25'} onClick={() => setLimit('25')}>First 25</button><button aria-pressed={limit === 'all'} onClick={() => setLimit('all')}>All FBS</button></div>
      </div>
    </div>
    {loading && !data && <p role="status">Reading college ratings…</p>}{error && <p role="alert">{error}</p>}
    {data && !data.available && <p className="empty-state">No college ratings for {season}. Use Refresh to load results.</p>}
    {data?.sources.some(s => s.error) && <p className="data-warning" role="alert">Results refresh failed. {data.available ? 'Saved ratings retained.' : 'Ratings unavailable.'} See sources below.</p>}
    {!!data?.awaiting_final_count && <p className="data-warning">{data.awaiting_final_count} started games await confirmed finals and have not changed ratings.</p>}
    {data?.available && <>
      <div className="cfb-board-caption"><span>{teams.length} of {data.teams?.length} FBS teams{query && ' · Search includes all FBS'}</span><span>{data.latest_result ? `Results through ${new Date(data.latest_result).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}` : 'No rated results yet'}</span></div>
      <div className="cfb-standing-grid cfb-standing-heading" aria-hidden="true"><span>Rank</span><span>Team</span><span>Strength</span><span>{scheduleLabel}</span><span className="cfb-last-change">Last Δ</span><span /></div>
      <ol className="league-leaderboard cfb-standings" aria-label="FBS strength rankings">
        {teams.map(t => <li key={t.id} style={collegeTeamStyle(t.id)}><details className="leaderboard-team cfb-standing">
          <summary className="cfb-standing-grid" aria-label={`${t.name} · Strength rank ${t.rank} · Supporting stats`}>
            <span className="leaderboard-rank">{rank(t.rank)}</span>
            <span className="cfb-standing-team"><img src={`https://a.espncdn.com/i/teamlogos/ncaa/500/${t.id}.png`} alt="" width="28" height="28" loading="lazy" onError={e => { e.currentTarget.hidden = true }} /><span>{t.name}<small>{record(t.record)}{t.notices.length > 0 && ' · Coverage notice'}</small></span></span>
            <span className="cfb-standing-value"><span className="sr-only">Strength </span>{number(t.rating)}</span>
            <span className="cfb-standing-schedule"><span className="sr-only">{scheduleLabel} </span>{rank(sort === 'opponents_now' ? t.opponents_now_rank : t.schedule_faced_rank)}</span>
            <span className="cfb-last-change"><span className="sr-only">Last change </span>{change(t.last_change)}</span>
          </summary>
          <div className="leaderboard-support">
            <dl className="supporting-stats"><div><dt>FBS record</dt><dd>{record(t.fbs_record)}</dd></div><div><dt>Vs strength top 25</dt><dd>{record(t.vs_current_top25)}</dd></div><div><dt>Schedule faced</dt><dd>{rank(t.schedule_faced_rank)}</dd></div><div><dt>Opponents now</dt><dd>{rank(t.opponents_now_rank)}</dd></div><div><dt>Season change</dt><dd>{change(t.season_change)}</dd></div><div><dt>Last change</dt><dd>{change(t.last_change)}</dd></div></dl>
            {t.notices.map(notice => <p className="data-warning" key={notice}>{notice}</p>)}
            <button className="prop-log-button" onClick={() => setInspect(t.id)} aria-label={`Open ${t.name} results and rating history`}>Results & rating history <span aria-hidden="true">↗</span></button>
          </div>
        </details></li>)}
      </ol>
      {!teams.length && <p className="empty-state">No matching FBS teams.</p>}
      <p className="source-note">Deck strength ranks · Lower SoS rank means harder opposition. Expand a team for records and result history.</p>
    </>}
    {data && <RatingSources data={data} />}
    {selected && <TeamEvidence team={selected} onClose={() => setInspect(null)} />}
  </section>
}
