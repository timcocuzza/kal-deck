import { useEffect, useRef, useState } from 'react'
import { matchupStyle, teamStyle } from './teamColors'
import { useReport } from './useReport'
import { askPrice, Dropdown, useHash, navigate } from './ui'
import { TeamComparison } from './TeamComparison'
import { PlayerPropsView } from './PlayerPropsView'
import { SpreadHistory, WeekHistoryButton } from './SpreadHistoryPanel'
import { PositionDefenseView } from './PositionDefenseView'
import type { BetSelection } from './TrackerView'
import { WatchButton } from './Watchlist'
import { EloCard, EloSources, EloTeamDialog, useElo } from './EloView'
import type { EloTeam } from './elo'

type Research = {
  coverage: { man_percentage: number; zone_percentage: number } | null
  coverage_note: string
  injuries: { player_name: string; position: string; injury: string | null; practice_status: string | null; game_status: string | null }[]
  injury_note: string; injuries_available: boolean
  depth: { player_name: string; pos_grp: string; pos_name: string; pos_rank: string }[]
  depth_date: string | null
}
type Team = { code: string; name: string; logo: string | null; research: Research }
type Market = {
  ticker: string; label: string; midpoint: number | null; wording: string; rules: string
  yes_bid_dollars: string | null; yes_ask_dollars: string | null
  no_bid_dollars: string | null; no_ask_dollars: string | null
}
type Game = {
  game_id: string; kickoff: string | null; date: string; week: number; home: Team; away: Team
  neutral: boolean; stadium: string | null; markets: Market[]; default_market_ticker: string | null; spread_status: string
}
type Source = {
  name: string; label: string; fetched_at: string | null; source_updated_at?: string | null
  error: string | null; url?: string; warnings?: string[]
}
type Matchups = {
  week: number; weeks: number[]; games: Game[]; warnings: string[]
  issues: { event: string | null; market?: string; reason: string }[]; sources: Source[]
}

function date(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString(undefined, { timeZoneName: 'short' }) : 'Not supplied'
}
function TeamLabel({ team }: { team: Team }) {
  return <span className="team-label" style={teamStyle(team.code)}>{team.logo && <img src={team.logo} alt="" width="36" height="36"
    onError={event => { event.currentTarget.style.display = 'none' }} />}<span>{team.name}</span></span>
}
function Quote({ market }: { market: Market }) {
  return <div className="spread-quote"><span>{market.label}</span><strong>{askPrice(market.yes_ask_dollars)}</strong><small>Yes ask · before fees</small></div>
}
function SourceNote({ source }: { source?: Source }) {
  return <p className="source-note">
    {source?.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.label}</a> : source?.label ?? 'Source unavailable'}
    {' · Fetched: '}{date(source?.fetched_at)}{' · Source update: '}{date(source?.source_updated_at)}
    {source?.error && <span> · Refresh failed: {source.error}. Using saved data where available.</span>}
  </p>
}
function TeamResearch({ team, sources }: { team: Team; sources: Source[] }) {
  const research = team.research
  return <article className="team-research" style={teamStyle(team.code)}>
    <h3><TeamLabel team={team} /></h3>
    <details><summary>Man / zone coverage</summary>
    <p>{research.coverage ? `Man ${research.coverage.man_percentage}% · Zone ${research.coverage.zone_percentage}%` : 'Coverage unavailable.'}</p>
    <p className="source-note">{research.coverage_note} Published percentages may not total 100%.</p>
    <SourceNote source={sources.find(s => s.name === 'coverage')} />
    </details><details><summary>Injury report</summary>
    <p>{research.injury_note}</p>
    <SourceNote source={sources.find(s => s.name === 'injuries')} />
    {research.injuries_available && <div className="table-scroll"><table>
      <caption>{team.code} injury report · reported statuses</caption>
      <thead><tr><th scope="col">Player</th><th scope="col">Injury</th><th scope="col">Practice</th><th scope="col">Game status</th></tr></thead>
      <tbody>{research.injuries.map((player, index) => <tr key={`${player.player_name}-${index}`}>
        <td>{player.player_name}<small className="metric-note">{player.position}</small></td>
        <td>{player.injury ?? 'Not reported'}</td><td>{player.practice_status ?? 'Not reported'}</td>
        <td>{player.game_status ?? 'Not reported'}</td>
      </tr>)}</tbody>
    </table></div>}
    </details><details><summary>Depth chart · {research.depth.length ? date(research.depth_date) : 'Unavailable'}</summary>
      <SourceNote source={sources.find(s => s.name === 'depth_charts')} />
      <div className="table-scroll"><table>
        <caption>{team.code} latest depth chart</caption>
        <thead><tr><th scope="col">Group / position</th><th scope="col">Depth</th><th scope="col">Player</th></tr></thead>
        <tbody>{research.depth.map((row, index) => <tr key={index}>
          <td>{row.pos_name}<small className="metric-note">{row.pos_grp}</small></td><td>{row.pos_rank}</td><td>{row.player_name}</td>
        </tr>)}</tbody>
      </table></div>
    </details>
  </article>
}

function dayKey(game: Game) {
  if (!game.kickoff) return game.date
  const d = new Date(game.kickoff)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function dayLabel(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}
function kickoff(game: Game) {
  return game.kickoff ? new Date(game.kickoff).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }) : 'Time unavailable'
}

export function MatchupsView({ season, revision, refreshing, onRecord }: {
  season: string; revision: number; refreshing: boolean; onRecord: (selection: BetSelection) => void
}) {
  const hash = useHash()
  const [path, query] = hash.split('?')
  const params = new URLSearchParams(query)
  let selected = ''
  try { if (path.startsWith('game/')) selected = decodeURIComponent(path.slice(5)) } catch { /* Unknown URL shows the grid. */ }
  const routeWeek = Number(params.get('week'))
  const [chosenWeek, setWeek] = useState<number | null>(null)
  const week = routeWeek >= 1 && routeWeek <= 18 ? routeWeek : chosenWeek
  useEffect(() => { if (routeWeek >= 1 && routeWeek <= 18) setWeek(routeWeek) }, [routeWeek])
  const [lastTab, setLastTab] = useState('stats')
  const tab = params.get('tab') === 'props' ? 'props' : params.get('tab') === 'stats' ? 'stats' : lastTab
  const { data, error, loading } = useReport<Matchups>(`/api/matchups?season=${season}${week === null ? '' : `&week=${week}`}`, revision)
  const [selectedMarket, setSelectedMarket] = useState<Record<string, string>>({})
  const [collapsed, setCollapsed] = useState(false)
  const [clock, setClock] = useState(Date.now())
  const elo = useElo(season, revision)
  const [eloTeam, setEloTeam] = useState<string | null>(null)
  const selectedEloTeam = elo.data?.available ? elo.data.teams.find(team => team.team === eloTeam) : undefined
  const openElo = (team: EloTeam) => setEloTeam(team.team)
  const homeScroll = useRef(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const previousGame = useRef(selected)
  useEffect(() => { setClock(Date.now()) }, [data])
  useEffect(() => {
    const starts = data?.games.flatMap(g => g.kickoff ? [new Date(g.kickoff).getTime()] : []).filter(t => t > clock) ?? []
    if (!starts.length) return
    const timer = window.setTimeout(() => setClock(Date.now()), Math.min(Math.max(0, Math.min(...starts) - Date.now()) + 10, 2147483647))
    return () => window.clearTimeout(timer)
  }, [data, clock])
  useEffect(() => {
    if (previousGame.current === selected) return
    const previous = previousGame.current
    previousGame.current = selected
    if (selected) { window.scrollTo({ top: 0 }); heading.current?.focus({ preventScroll: true }) }
    else if (path === 'games') { window.scrollTo({ top: homeScroll.current }); document.querySelector<HTMLButtonElement>(`[data-game-id="${CSS.escape(previous || history.state?.deckGame || '')}"]`)?.focus({ preventScroll: true }) }
  }, [selected, path])
  const games = data?.games.filter(game => !game.kickoff || new Date(game.kickoff).getTime() > clock) ?? []
  const game = games.find(item => item.game_id === selected)
  const market = game?.markets.find(item => item.ticker === (params.get('market') || selectedMarket[game.game_id]))
    ?? game?.markets.find(item => item.ticker === game.default_market_ticker)
  const watchEntry = (item: Game, contract: Market) => ({ kind: 'spread' as const, season: Number(season), week: item.week, game_id: item.game_id, ticker: contract.ticker, label: contract.label })
  const days = [...new Set(games.map(dayKey))].sort()
  function openGame(id: string) {
    if (!selected) { homeScroll.current = window.scrollY; history.replaceState({ ...history.state, deckGame: id }, '') }
    navigate(`game/${encodeURIComponent(id)}?week=${data?.week ?? week ?? 1}&tab=${tab}`)
  }
  function changeTab(next: string) { setLastTab(next); navigate(`game/${encodeURIComponent(selected)}?week=${data?.week ?? week ?? 1}&tab=${next}`, true) }
  const notices = <div className="matchup-notices"><EloSources {...elo} />
    {data && <details className="provenance"><summary>Sources & matching notices ({data.warnings.length + data.issues.length})</summary>
      {data.warnings.map(warning => <p key={warning}>{warning}</p>)}
      {data.sources.map(source => <div key={source.name}><SourceNote source={source} />{source.warnings?.map(warning => <p key={warning}>{warning}</p>)}</div>)}
      <ul>{data.issues.map((issue, index) => <li key={index}>{issue.event ?? 'Matching'}{issue.market ? ` · ${issue.market}` : ''}: {issue.reason}</li>)}</ul>
    </details>}
  </div>
  return <section className="matchups-view" aria-label="NFL matchups">
    {loading && !data && <p role="status" className="empty-state">Loading saved matchups…</p>}
    {error && <p role="alert">{error}{data && ' Showing previously loaded games.'}</p>}
    {data?.sources.some(source => source.error) && <p className="data-warning" role="status">Some source updates failed. Saved data remains visible; inspect source timestamps below.</p>}
    {!game ? <div className="games-home">
      <div className="page-heading"><div><h1 ref={heading} tabIndex={-1}>This week’s games</h1><p>Find your next matchup.</p></div><div className="controls">
        {data && <Dropdown label="NFL week" value={String(data.week)} options={(data.weeks.length ? data.weeks : [data.week]).map(value => ({ value: String(value), label: `Week ${value}` }))}
          onChange={value => { setWeek(Number(value)); navigate('games', true) }} />}
        <WeekHistoryButton tickers={games.flatMap(item => item.default_market_ticker ? [item.default_market_ticker] : [])} />
      </div></div>
      {selected && !loading && <p role="status">This game is unavailable or has started. <button onClick={() => navigate('games')}>Back to games</button></p>}
      {!loading && data && !games.length && <p className="empty-state">No unstarted games remain in this week’s saved schedule. Choose another week.</p>}
      {days.map(day => <section key={day} className="game-day"><h2 className="day-heading">{dayLabel(day)}<small>{games.filter(game => dayKey(game) === day).length} games</small></h2>
        <div className="game-cards">{games.filter(game => dayKey(game) === day).map(item => {
          const defaultMarket = item.markets.find(market => market.ticker === item.default_market_ticker)
          return <article key={item.game_id} className="game-card" style={matchupStyle(item.away.code, item.home.code)}>
            <button className="game-open" data-game-id={item.game_id} onClick={() => openGame(item.game_id)} aria-label={`Open ${item.away.name} ${item.neutral ? 'versus' : 'at'} ${item.home.name}`}>
              <span className="game-time">{kickoff(item)}{item.neutral && ' · Neutral site'}<span aria-hidden="true">↗</span></span>
              <TeamLabel team={item.away} /><TeamLabel team={item.home} />
            </button>
            <div className="game-market">{defaultMarket ? <><button className="game-spread" onClick={() => openGame(item.game_id)}><Quote market={defaultMarket} /></button>
              <SpreadHistory key={defaultMarket.ticker} ticker={defaultMarket.ticker} label={defaultMarket.label} compact /></> : <small>{item.spread_status}</small>}</div>
            {defaultMarket && <WatchButton entry={watchEntry(item, defaultMarket)} />}
            <EloCard data={elo.data} game={item} onTeam={openElo} />
          </article>
        })}</div>
      </section>)}
      <footer className="home-foot"><span>Yes ask prices before fees · History lines show the midpoint</span><span>Saved quotes · Refresh on open</span></footer>
      {notices}
    </div> : <div className={`detail-layout${collapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className="game-sidebar" aria-label="This week’s games"><button className="back-link" onClick={() => navigate('games')}>← All games</button>
        {days.map(day => <section key={day}><h2>{dayLabel(day)}</h2>{games.filter(game => dayKey(game) === day).map(item => <button className="sidebar-game" key={item.game_id} aria-current={item.game_id === selected ? 'page' : undefined} onClick={() => openGame(item.game_id)}>
          <span>{item.away.code} {item.neutral ? 'vs' : 'at'} {item.home.code}</span><small>{kickoff(item)}</small></button>)}</section>)}
      </aside>
      <div className="matchup-detail" style={matchupStyle(game.away.code, game.home.code)}><div className="detail-toolbar"><button className="sidebar-toggle" onClick={() => setCollapsed(!collapsed)}>{collapsed ? 'Show games' : 'Hide games'}</button>
        <div className="mobile-game-switch"><Dropdown label="Switch game" value={game.game_id} options={games.map(item => ({ value: item.game_id, label: `${item.away.code} ${item.neutral ? 'vs' : 'at'} ${item.home.code}` }))} onChange={openGame} /></div>
        <button className="back-link" onClick={() => navigate('games')}>All games ↗</button></div>
        <div className="detail-heading"><div className="matchup-logos">{[game.away, game.home].map(team => team.logo && <img key={team.code} src={team.logo} alt="" width="44" height="44" />)}</div>
          <div><h1 ref={heading} tabIndex={-1}>{game.away.name} <span>{game.neutral ? 'vs' : 'at'}</span> {game.home.name}</h1><p>{date(game.kickoff)} · Week {data?.week} · {game.stadium}</p></div></div>
        <nav className="detail-tabs" aria-label="Matchup views"><button aria-pressed={tab === 'stats'} onClick={() => changeTab('stats')}>Stats</button><button aria-pressed={tab === 'props'} onClick={() => changeTab('props')}>Player props</button></nav>
        {tab === 'props' ? <PlayerPropsView key={`${season}:${game.game_id}`} gameId={game.game_id} season={season} revision={revision} refreshing={refreshing} onRecord={onRecord}
          initialTicker={params.get('market') ?? ''} teamLogos={{ [game.away.code]: game.away.logo, [game.home.code]: game.home.logo }} /> : <>
          <section className="spread-panel"><div className="section-heading"><Dropdown label="Available spread" value={market?.ticker ?? ''} disabled={!game.markets.length}
            options={[...(!market ? [{ value: '', label: 'Select a spread' }] : []), ...game.markets.map(item => ({ value: item.ticker, label: item.label }))]}
            onChange={value => { setSelectedMarket(current => ({ ...current, [game.game_id]: value }));
              navigate(`game/${encodeURIComponent(game.game_id)}?week=${game.week}&tab=stats&market=${encodeURIComponent(value)}`, true) }} />
            {market && <Quote market={market} />}</div>
            {market ? <><WatchButton entry={watchEntry(game, market)} /><SpreadHistory key={market.ticker} ticker={market.ticker} label={market.label} />
              <details className="provenance"><summary>Contract wording & quotes</summary><p>{market.wording}</p><p>{market.rules}</p><p>No ask: {askPrice(market.no_ask_dollars)} · before fees</p><small>{market.ticker}</small></details>
              <button onClick={() => onRecord({ description: `${game.away.name} vs ${game.home.name}: ${market.wording}`, selection: '', market_ticker: market.ticker, game_id: game.game_id })}>Record a bet on this spread</button></> : <p>{game.spread_status}</p>}
          </section>
          <EloCard data={elo.data} game={game} onTeam={openElo} />
          <TeamComparison key={game.game_id} season={season} revision={revision} teams={[game.away.code, game.home.code]} />
          <details className="research-expand"><summary>Defense by player position</summary><PositionDefenseView key={`position-${game.game_id}`} season={season} revision={revision} refreshing={refreshing} teamCodes={[game.away.code, game.home.code]} /></details>
          <div className="team-research-grid"><TeamResearch team={game.away} sources={data!.sources} /><TeamResearch team={game.home} sources={data!.sources} /></div>
        </>}
        {notices}
      </div>
    </div>}
    {selectedEloTeam && <EloTeamDialog team={selectedEloTeam} season={season} onClose={() => setEloTeam(null)} />}
  </section>
}
