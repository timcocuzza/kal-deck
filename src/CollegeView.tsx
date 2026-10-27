import { MarginForecast } from './MarginForecast'
import type { MarginContract, MarginForecast as Forecast } from './margins'
import { useEffect, useState } from 'react'
import { useReport } from './useReport'
import { askPrice, Dropdown, Modal, navigate, useHash } from './ui'
import { SpreadHistory, WeekHistoryButton } from './SpreadHistoryPanel'
import { CollegeRatings, CollegeStrengthPair } from './CollegeRatings'
import { WatchButton } from './Watchlist'
import type { BetSelection } from './TrackerView'
import { collegeTeamStyle, collegeMatchupStyle } from './collegeColors'

type Source = { name: string; label?: string; url?: string; fetched_at: string | null; error: string | null; warnings?: string[];
  context?: { resources?: { dataset: string; url: string; source_updated_at: string | null }[] } }
type Team = { id: string; name: string; is_fbs: boolean; division: string; logo: string | null }
type Market = MarginContract & { ticker: string; label: string; yes_ask_dollars: string | null; midpoint: number | null; wording: string; rules: string; rules_secondary: string }
type Game = { margin_forecast?: Forecast; game_id: string; season_type: 'regular' | 'postseason'; week: number; kickoff: string; time_tbd: boolean; neutral: boolean; venue: string | null; home: Team; away: Team;
  schedule_verified: boolean; participants_confirmed: boolean; status: string; markets: Market[]; default_market_ticker: string | null; spread_status: string }
type BaseReport = { available: boolean; warnings: string[]; sources: Source[]; issues?: { event?: string; market?: string; reason: string }[] }
type Schedule = BaseReport & { season_type?: 'regular' | 'postseason'; periods?: { season_type: 'regular' | 'postseason'; week: number }[]; week?: number; weeks?: number[]; games?: Game[]; overdue_games?: number }
type Support = { value: number | null; label?: string; games_used?: number; games_expected?: number }
type Facet = {
  value: number | null; rank: number | null; games_used: number; games_expected: number
  league: { mean: number | null; median: number | null; teams_ranked: number; teams_expected: number }
  supporting: Record<string, Support>
  schedule_context: { average_opponent_metric: number | null; opponents_used: number; games_expected: number }
  games: { game_id: string; date: string; opponent: string; opponent_is_fbs: boolean; value: number | null; opponent_current_rank: number | null; opponent_current_metric: number | null }[]
}
type Category = { key: string; label: string; measure: string; opposing: string; higher_is_better: boolean }
type Rankings = BaseReport & {
  teams?: Record<string, { name: string; categories: Record<string, Facet> }>
  categories?: Category[]; latest_completed_kickoff?: string | null; team_count?: number; missing_completed_games?: number
}
const format = (value: number | null | undefined) => value == null ? 'Unavailable' : value.toLocaleString(undefined, { maximumFractionDigits: 3 })
const rank = (value: number | null | undefined) => value == null ? 'Unranked' : `#${value}`
const date = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
function when(game: Game) {
  if (game.status === 'STATUS_POSTPONED') return 'Postponed · Kickoff unconfirmed'
  return game.time_tbd ? `${date(game.kickoff)} · Time TBD` : new Date(game.kickoff).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}
function TeamName({ team }: { team: Team }) {
  return <span className="team-label" style={collegeTeamStyle(team.id)}>{team.logo && <img src={team.logo} alt="" width="36" height="36" onError={event => { event.currentTarget.hidden = true }} />}
    <span>{team.name}{!team.is_fbs && <small className="metric-note">{team.division === 'fcs' ? 'FCS · Team statistics not provided' : 'Participant unconfirmed'}</small>}</span></span>
}
function Sources({ report }: { report: BaseReport }) {
  return <details className="provenance"><summary>Sources & methodology</summary>
    {report.warnings.map(warning => <p key={warning}>{warning}</p>)}
    {report.issues?.map((issue, i) => <p key={i}>{issue.event && `${issue.event}: `}{issue.reason}</p>)}
    {report.sources.map(source => <div key={source.name}><p>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.label ?? source.name}</a> : source.label ?? source.name} · Saved: {source.fetched_at ? new Date(source.fetched_at).toLocaleString() : 'Not downloaded'}</p>
      {source.error && <p role="alert">Refresh failed: {source.error}</p>}
      {source.context?.resources?.map(resource => <p key={resource.dataset}><a href={resource.url} target="_blank" rel="noreferrer">{resource.dataset.replaceAll('_', ' ')}</a> · Source updated: {resource.source_updated_at ? new Date(resource.source_updated_at).toLocaleString() : 'Not supplied'}</p>)}
      {source.warnings?.map(warning => <p key={warning}>{warning}</p>)}</div>)}
  </details>
}

function Comparison({ game, season, revision }: { game: Game; season: string; revision: number }) {
  const [includeFcs, setIncludeFcs] = useState(false)
  const [sameUnits, setSameUnits] = useState(false)
  const [inspection, setInspection] = useState<{ team: Team; category: string } | null>(null)
  const { data, error, loading } = useReport<Rankings>(`/api/cfb/rankings?season=${season}&game_id=${game.game_id}&include_fcs=${includeFcs}`, revision)
  const teams = [game.away, game.home]
  const definition = (key: string) => data?.categories?.find(c => c.key === key)
  const log = inspection && data?.teams?.[inspection.team.id]?.categories[inspection.category]
  const labels: Record<string, string> = { yards_per_game: 'Rushing yards / game', yards_per_attempt: 'Yards / attempt', yards_per_carry: 'Yards / carry', completion_fraction: 'Completion rate', interceptions: 'Interceptions', touchdowns: 'Touchdowns', positive_epa_success_fraction: 'Positive EPA rush rate' }
  function supportValue(key: string, metric: Support) {
    return <>{format(metric.value == null ? null : key.endsWith('fraction') ? metric.value * 100 : metric.value)}{key.endsWith('fraction') && metric.value != null ? '%' : ''}
      {metric.games_used != null && <small> · {metric.games_used}/{metric.games_expected} games</small>}</>
  }
  return <section className="team-comparison" aria-label="College team comparison">
    <div className="section-heading"><h2>Team comparison</h2><div className="segmented" aria-label="Comparison mode">
      <button aria-pressed={!sameUnits} onClick={() => setSameUnits(false)}>Opposing units</button>
      <button aria-pressed={sameUnits} onClick={() => setSameUnits(true)}>Same units</button>
    </div></div>
    <div className="controls"><Dropdown label="Games counted" value={includeFcs ? 'all' : 'fbs'} onChange={value => { setIncludeFcs(value === 'all'); setInspection(null) }}
      options={[{ value: 'fbs', label: 'FBS opponents only' }, { value: 'all', label: 'Include FBS performances against FCS' }]} /></div>
    <p className="source-note">FCS teams never receive rankings or season statistics. This choice changes which games count for FBS teams.</p>
    {loading && !data && <p role="status">Calculating saved college rankings…</p>}{error && <p role="alert">{error}</p>}
    {data?.sources.some(source => source.error) && <p className="data-warning">Refresh failed · Saved statistics remain visible.</p>}
    {data && !data.available && <p className="empty-state">No saved college statistics for {season}. Use Refresh to download them.</p>}
    {data?.available && <><p className="data-warning">Published EPA · Rounded source values; scrambles count as rushes.</p>
      <p className="source-note">{data.team_count} source-classified FBS teams · Latest game with all statistics tables: {data.latest_completed_kickoff ? date(data.latest_completed_kickoff) : 'Unavailable'}.</p>
      {!!data.missing_completed_games && <p className="data-warning">{data.missing_completed_games} completed games have missing statistics. Rankings exclude unavailable values; coverage counts include those games.</p>}
      <div className="comparison-grid">{data.categories?.map(category => {
        const keys = [category.key, sameUnits ? category.key : category.opposing]
        const columns = teams.map((team, side) => ({ team, key: keys[side], metric: data.teams?.[team.id]?.categories[keys[side]], def: definition(keys[side]) }))
        return <article className="comparison-card" key={category.key}>
          <div className="compare-head">{teams.map(team => <span key={team.id} style={collegeTeamStyle(team.id)}>{team.name}</span>)}</div>
          <div className="compare-columns">{columns.map(({ team, key, metric, def }) => <button className="rank-tile" key={team.id} style={collegeTeamStyle(team.id)} disabled={!metric || !team.is_fbs}
            onClick={() => setInspection({ team, category: key })} aria-label={`${team.name} ${def?.label}: ${team.is_fbs ? `${rank(metric?.rank)}, ${format(metric?.value)} ${def?.measure}. Open game log` : 'FCS statistics not provided'}`}>
            <strong>{team.is_fbs ? rank(metric?.rank) : 'Not provided'}</strong><span>{def?.label}<small>{team.is_fbs ? format(metric?.value) : 'FCS team'} {team.is_fbs && def?.measure}</small></span>
            {metric && <><small>{def?.higher_is_better ? 'Higher' : 'Lower'} is better · {metric.games_used}/{metric.games_expected} games{metric.games_used < metric.games_expected && ' · Incomplete'}</small>
              <small className="league-context">League mean {format(metric.league.mean)} · Median {format(metric.league.median)} · {metric.league.teams_ranked}/{metric.league.teams_expected} teams</small></>}
          </button>)}</div>
          <div className="college-opponents"><h3>Opponent strength faced</h3><div className="support-pair">{columns.map(({ team, metric, def }) => <dl key={team.id}>
            <dt>{definition(def?.opposing ?? '')?.label} · {definition(def?.opposing ?? '')?.higher_is_better ? 'Higher' : 'Lower'} is stronger</dt>
            <dd>{team.is_fbs ? format(metric?.schedule_context.average_opponent_metric) : 'Not provided'}
              {metric && <small>{metric.schedule_context.opponents_used}/{metric.schedule_context.games_expected} opponents · {definition(def?.opposing ?? '')?.measure}</small>}</dd>
          </dl>)}</div></div>
          <details className="support-details"><summary>Supporting stats</summary><div className="support-body">
            {Array.from({ length: Math.max(0, ...columns.map(c => Object.keys(c.metric?.supporting ?? {}).length)) }, (_, i) => <div className="support-pair" key={i}>{columns.map(column => {
              const entry = Object.entries(column.metric?.supporting ?? {})[i]
              return <dl key={column.team.id}><dt>{entry ? entry[1].label ?? labels[entry[0]] ?? entry[0] : 'Statistics'}</dt><dd>{entry ? supportValue(entry[0], entry[1]) : 'Not provided'}</dd></dl>
            })}</div>)}
          </div></details>
        </article>
      })}</div></>}
    {data && <Sources report={data} />}
    {inspection && log && <Modal title={`${inspection.team.name} · ${definition(inspection.category)?.label}`} onClose={() => setInspection(null)}>
      <p className="source-note">Current opponent ranks · {definition(definition(inspection.category)?.opposing ?? '')?.label} · {includeFcs ? 'Including FBS performances against FCS' : 'FBS opponents only'}</p>
      <div className="table-scroll"><table><thead><tr><th>Date</th><th>Opponent</th><th>{definition(inspection.category)?.measure}</th><th>Opponent rank</th><th>Opponent season value</th></tr></thead>
        <tbody>{log.games.map(row => <tr key={row.game_id}><td>{date(row.date)}</td><td>{row.opponent}{!row.opponent_is_fbs && ' · FCS'}</td><td>{format(row.value)}</td>
          <td>{row.opponent_is_fbs ? rank(row.opponent_current_rank) : 'Not provided'}</td><td>{row.opponent_is_fbs ? format(row.opponent_current_metric) : 'Not provided'}</td></tr>)}</tbody></table></div>
      {!log.games.length && <p>No completed games in this scope.</p>}
    </Modal>}
  </section>
}

function watchEntry(game: Game, market: Market, season: string) {
  return { sport: 'cfb' as const, season_type: game.season_type, ticker: market.ticker, kind: 'spread' as const,
    season: Number(season), week: game.week, game_id: game.game_id, label: `${game.away.name} vs ${game.home.name} · ${market.label}` }
}

function SpreadPanel({ game, season, selected, onSelect, source, onRecord }: { game: Game; season: string; onRecord: (selection: BetSelection) => void; selected: string | null; onSelect: (ticker: string) => void; source?: Source }) {
  const market = game.markets.find(item => item.ticker === selected)
    ?? game.markets.find(item => item.ticker === game.default_market_ticker)
  return <section className="spread-panel" aria-label="College spreads"><div className="section-heading"><h2>Spreads</h2>
    {!!game.markets.length && <Dropdown label="College spread" value={market?.ticker ?? ''} options={game.markets.map(item => ({ value: item.ticker, label: item.label }))} onChange={onSelect} />}
    {market && <div className="spread-quote"><span>{market.label}</span><strong>{askPrice(market.yes_ask_dollars)}</strong><small>Yes ask · before fees</small></div>}
  </div>
    <MarginForecast forecast={game.margin_forecast} home={game.home.name} away={game.away.name} contract={market} />
    {selected && !game.markets.some(item => item.ticker === selected) && <p role="status">The previously selected contract is no longer available in the verified snapshot.</p>}
    {!market && <p>{game.spread_status}{game.markets.length ? ' · Select a verified contract to inspect it.' : ' · Research remains available.'}</p>}
    <p className="source-note">Saved quotes: {source?.fetched_at ? new Date(source.fetched_at).toLocaleString() : 'Not downloaded'}{source?.error && ' · Refresh failed; previous quotes retained.'}</p>
    {market && <><WatchButton entry={watchEntry(game, market, season)} /><SpreadHistory key={market.ticker} ticker={market.ticker} label={market.label} />
      <button onClick={() => onRecord({ description: `${game.away.name} vs ${game.home.name}: ${market.wording}`, selection: '', market_ticker: market.ticker, game_id: game.game_id })}>Record a bet on this spread</button>
      <details className="provenance"><summary>Contract wording and settlement rules</summary><p>{market.wording}</p><p>{market.rules}</p><p className="college-rules">{market.rules_secondary}</p></details></>}
  </section>
}

export function CollegeView({ season, revision, onSeason, onRecord }: { season: string; revision: number; onSeason: (season: string) => void; onRecord: (selection: BetSelection) => void }) {
  const hash = useHash()
  const [path, query] = hash.split('?')
  const params = new URLSearchParams(query)
  const phase = params.get('season_type')
  const requestedWeek = params.get('week')
  const week = requestedWeek !== null && /^\d{1,2}$/.test(requestedWeek) && Number(requestedWeek) <= 30 ? requestedWeek : null
  const selected = /^cfb\/game\/(\d+)$/.exec(path)?.[1]
  const { data, error, loading } = useReport<Schedule>(`/api/cfb/matchups?season=${season}${week !== null ? `&week=${week}` : ''}${phase === 'regular' || phase === 'postseason' ? `&season_type=${phase}` : ''}`, revision)
  const period = (game?: Game) => `week=${game?.week ?? data?.week ?? 1}&season_type=${game?.season_type ?? data?.season_type ?? 'regular'}`
  const [clock, setClock] = useState(Date.now)
  useEffect(() => {
    const next = Math.min(...(data?.games ?? []).filter(g => !g.time_tbd && g.status !== 'STATUS_POSTPONED')
      .map(g => new Date(g.kickoff).getTime()).filter(t => t > Date.now()))
    if (!Number.isFinite(next)) return
    const timer = setTimeout(() => setClock(Date.now()), Math.min(next - Date.now() + 50, 2147483647))
    return () => clearTimeout(timer)
  }, [data, clock])
  const games = (data?.games ?? []).filter(g => g.time_tbd || g.status === 'STATUS_POSTPONED' || new Date(g.kickoff).getTime() > Math.max(clock, Date.now()))
  const game = games.find(item => item.game_id === selected)
  const days = [...new Set(games.map(item => date(item.kickoff)))]
  if (path === 'cfb/ratings') return <CollegeRatings season={season} revision={revision} onSeason={onSeason} />
  return <section className="matchups-view college-view" aria-label="College football">
    <div className="page-heading"><div><h1>College football</h1><p className="source-note">FBS games & spreads</p></div><div className="controls">
      <Dropdown label="College season" value={season} options={[...new Set([Number(season), ...Array.from({ length: 6 }, (_, i) => new Date().getFullYear() + 1 - i)])].sort((a, b) => b - a).map(year => ({ value: String(year), label: String(year) }))} onChange={value => { onSeason(value); navigate('cfb') }} />
      {!!data?.periods?.length && <Dropdown label="College week" value={`${data.season_type}:${data.week}`} options={data.periods.map(p => ({ value: `${p.season_type}:${p.week}`, label: p.season_type === 'postseason' ? `Bowls & CFP${p.week === 1 ? '' : ` · Week ${p.week}`}` : `Week ${p.week}` }))} onChange={value => { const [phase, week] = value.split(':'); navigate(`cfb?week=${week}&season_type=${phase}`) }} />}
      {!!games.length && <WeekHistoryButton tickers={games.flatMap(g => g.default_market_ticker ? [g.default_market_ticker] : [])} />}
    </div></div>
    {loading && !data && <p role="status">Loading saved college schedule…</p>}{error && <p role="alert">{error}</p>}
    {data?.sources.some(source => source.error) && <p className="data-warning">A college source update failed · Saved data retained. See Data for details.</p>}
    {data && !data.available && <p className="empty-state">No college snapshot for {season}. Use Refresh to download free schedule and statistics data.</p>}
    {selected && !game && !loading && <p role="status">This game has started or is absent from the saved week. <button onClick={() => navigate(`cfb?${period()}`)}>Back to games</button></p>}
    {game ? <div className="matchup-detail" style={collegeMatchupStyle(game.away.id, game.home.id)}><button className="back-link" onClick={() => navigate(`cfb?${period()}`)}>← All college games</button>
      <div className="detail-heading"><div className="matchup-logos">{[game.away, game.home].map(team => team.logo && <img key={team.id} src={team.logo} alt="" width="44" height="44" />)}</div><div><h2>{game.away.name} {game.neutral ? 'vs' : 'at'} {game.home.name}</h2><p>{when(game)}{game.venue && ` · ${game.venue}`}{game.neutral && ' · Neutral site'}</p></div></div>
      <SpreadPanel game={game} season={season} onRecord={onRecord} selected={params.get('market')} onSelect={ticker => navigate(`cfb/game/${game.game_id}?${period(game)}&market=${encodeURIComponent(ticker)}`, true)} source={data?.sources.find(s => s.name === 'cfb_markets')} />
      <CollegeStrengthPair season={season} revision={revision} ids={[game.away.id, game.home.id]} />
      {game.participants_confirmed ? <Comparison key={game.game_id} game={game} season={season} revision={revision} /> : <p>Participants have not been confirmed. Team comparisons will be available when their identities are known.</p>}
    </div> : <>{data?.available && !games.length && <p className="empty-state">No unstarted games remain in this week’s saved schedule. Choose another week.</p>}
      {days.map(day => <section className="game-day" key={day}><h2 className="day-heading">{day}<small>{games.filter(item => date(item.kickoff) === day).length} games</small></h2><div className="game-cards">
        {games.filter(item => date(item.kickoff) === day).map(item => <article className="game-card" key={item.game_id} style={collegeMatchupStyle(item.away.id, item.home.id)}>
          <button className="game-open" onClick={() => navigate(`cfb/game/${item.game_id}?${period(item)}`)} aria-label={`Open ${item.away.name} at ${item.home.name}`}>
            <span className="game-time">{when(item)}{item.neutral && ' · Neutral site'}<span aria-hidden="true">↗</span></span><TeamName team={item.away} /><TeamName team={item.home} />
          </button><div className="game-market">{(() => {
            const market = item.markets.find(m => m.ticker === item.default_market_ticker)
            return market ? <><button className="game-spread" onClick={() => navigate(`cfb/game/${item.game_id}?${period(item)}`)}><div className="spread-quote"><span>{market.label}</span><strong>{askPrice(market.yes_ask_dollars)}</strong><small>Yes ask · before fees</small></div></button><WatchButton entry={watchEntry(item, market, season)} /><SpreadHistory ticker={market.ticker} label={market.label} compact /></> : <small>{item.spread_status}</small>
          })()}</div><MarginForecast forecast={item.margin_forecast} home={item.home.name} away={item.away.name} contract={item.markets.find(m => m.ticker === item.default_market_ticker)} compact /><CollegeStrengthPair season={season} revision={revision} ids={[item.away.id, item.home.id]} />
        </article>)}
      </div></section>)}</>}
    {data && <Sources report={data} />}
  </section>
}
