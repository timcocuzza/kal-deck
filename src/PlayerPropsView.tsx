import { teamStyle } from './teamColors'
import { useState } from 'react'
import { useReport } from './useReport'
import { askPrice, Dropdown, Modal } from './ui'
import type { BetSelection } from './TrackerView'
import { PositionDefenseView } from './PositionDefenseView'
import type { PositionReport } from './PositionDefenseView'
import { LeagueContext, MetricValue, RankingInspection } from './RankingsView'
import type { RankingReport } from './RankingsView'

type Source = { name: string; label: string; fetched_at: string | null; error: string | null }
type OpponentRank = { category: string; label: string; rank: number | null; incomplete: boolean; kind?: 'position' }
type Inspection = { team: string; category: string; kind?: 'position' }
type Contract = {
  ticker: string; threshold: number; label: string; title: string; rules: string; rules_secondary: string
  midpoint: number | null; yes_bid_dollars: string | null; yes_ask_dollars: string | null
  no_bid_dollars: string | null; no_ask_dollars: string | null
}
type Group = {
  key: string; category: string; label: string
  player: { id: string; kalshi_id: string; name: string; team: string; position: string }
  markets: Contract[]
  opponent: string; position_categories: string[]; opponent_ranks?: OpponentRank[]
}
type PropsReport = {
  groups: Group[]; categories: { key: string; label: string }[]; sources: Source[]; warnings: string[]
  issues: { market: string; reason: string }[]; unsupported: { series: string; label: string; events: string[] }[]
}
type Log = {
  label: string; note: string; warnings: string[]; sources: Source[]
  games: {
    game_id: string; date: string; week: number; team: string; opponent: string; value: number | null
    components: Record<string, number | null>
    opponent_ranks: OpponentRank[]
  }[]
}

function Sources({ sources }: { sources: Source[] }) {
  return <details className="provenance"><summary>Source timestamps and refresh status</summary><ul>
    {sources.map(source => <li key={source.name}>{source.label}: {source.fetched_at ? new Date(source.fetched_at).toLocaleString() : 'Not downloaded'}
      {source.error && <span> · Refresh failed: {source.error}. Saved data may be out of date.</span>}
    </li>)}
  </ul></details>
}
function PlayerLog({ group, season, revision, threshold, onInspect }: { group: Group; season: string; revision: number; threshold: number | undefined; onInspect: (value: Inspection) => void }) {
  const { data, error, loading } = useReport<Log>(`/api/players/${encodeURIComponent(group.player.id)}/games?season=${season}&category=${group.category}`, revision)
  return <section aria-label={`${group.player.name} game log`} className="player-log">
    <h3>{group.player.name} · {group.label} · {season} game log</h3>
    {loading && <p role="status">Loading saved player statistics…</p>}
    {error && <p role="alert">{error}</p>}
    {data && <>
      <p className="source-note">{data.note}</p>
      <Sources sources={data.sources} />
      {data.sources.some(s => s.error) && <p role="status">A source refresh failed; check the saved-data timestamps above.</p>}
      {data.warnings.map((warning, index) => <p role="status" key={index}>{warning}</p>)}
      {!data.games.length ? <p>No verified completed player-game rows are available in the saved data.</p> : <div className="table-scroll"><table>
        <caption>{group.player.name} · official game statistics and opponent’s current ranks</caption>
        <thead><tr><th scope="col">Week / date</th><th scope="col">Team / opponent</th><th scope="col">{data.label}</th><th scope="col">At {threshold ?? "—"}+</th><th scope="col">Opponent’s current rank</th></tr></thead>
        <tbody>{data.games.map(game => <tr key={game.game_id}>
          <td>{game.week}<small className="metric-note">{game.date}</small></td>
          <td>{game.team} vs {game.opponent}</td>
          <td>{game.value === null ? 'Unavailable' : game.value.toLocaleString()}
            {group.category === 'rushing_receiving_yards' && <small className="metric-note">
              Rush {game.components.rushing_yards ?? 'Unavailable'} · Rec {game.components.receiving_yards ?? 'Unavailable'}
            </small>}
          </td>
          <td className={game.value == null || threshold == null ? "" : game.value >= threshold ? "threshold-met" : "threshold-below"}>{game.value == null || threshold == null ? "Unavailable" : game.value >= threshold ? "Met" : "Below"}</td>
          <td>{game.opponent_ranks.map(rank => <div key={rank.category}>
            <button onClick={() => onInspect({ team: game.opponent, category: rank.category, kind: rank.kind })}>
              {rank.label}: {rank.rank === null ? 'Unavailable' : `#${rank.rank}`}{rank.incomplete && ' · Incomplete'} · View log
            </button>
          </div>)}</td>
        </tr>)}</tbody>
      </table></div>}
    </>}
  </section>
}

export function PlayerPropsView({ gameId, season, revision, refreshing, onRecord, teamLogos = {} }: {
  gameId: string; season: string; revision: number; refreshing: boolean; onRecord: (selection: BetSelection) => void
  teamLogos?: Record<string, string | null>
}) {
  const { data, error, loading } = useReport<PropsReport>(`/api/matchups/${encodeURIComponent(gameId)}/props?season=${season}`, revision)
  const rankings = useReport<RankingReport>(`/api/rankings?season=${season}`, revision)
  const positions = useReport<PositionReport>(`/api/position-defense?season=${season}`, revision)
  const [category, setCategory] = useState('')
  const [teamFilter, setTeamFilter] = useState('all')
  const [selected, setSelected] = useState('')
  const [contracts, setContracts] = useState<Record<string, string>>({})
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const categoryValue = category || (data?.groups.some(group => group.category === 'receiving_yards') ? 'receiving_yards' : data?.groups[0]?.category ?? 'all')
  const groups = data?.groups.filter(group => (categoryValue === 'all' || group.category === categoryValue) && (teamFilter === 'all' || group.player.team === teamFilter)) ?? []
  const group = data?.groups.find(group => group.key === selected)
  const selectedMarket = (item: Group) => item.markets.find(market => market.ticker === contracts[item.key]) ?? item.markets[0]
  const market = group && selectedMarket(group)
  const teams = [...new Set(data?.groups.map(group => group.player.team) ?? [])]
  const thresholdPicker = (item: Group) => <Dropdown label={`${item.player.name} ${item.label} threshold`} value={selectedMarket(item)?.ticker ?? ''}
    options={item.markets.map(market => ({ value: market.ticker, label: market.label }))}
    onChange={ticker => setContracts(current => ({ ...current, [item.key]: ticker }))} />
  const context = (item: Group) => <div className="opponent-context"><small>Upcoming opponent · {item.opponent}</small>
    {item.opponent_ranks?.map(rank => {
      const position = rank.kind === 'position'
      const metric = position ? positions.data?.teams.find(team => team.team === item.opponent)?.categories[rank.category]?.headline
        : rankings.data?.teams.find(team => team.team === item.opponent)?.categories[rank.category]?.headline
      const definition = rankings.data?.categories.find(category => category.key === rank.category)
      const league = position ? positions.data?.league[rank.category] : rankings.data?.league?.categories[rank.category]
      return <div className="context-measure" key={rank.category}>
        <button className="context-rank" onClick={() => { setInspection({ team: item.opponent, category: rank.category, kind: rank.kind }); setSelected('') }}>
          <span>{rank.label}</span><strong>{metric?.rank == null ? 'Unavailable' : `#${metric.rank}`}</strong></button>
        {metric && <><small><MetricValue metric={metric} /> {position ? 'yards allowed/game' : definition?.measure}</small>
          <LeagueContext summary={league} /><small className="metric-note">{position || !definition?.higher_is_better ? 'Lower' : 'Higher'} is better</small></>}
      </div>
    })}
    {(!item.opponent_ranks || !item.opponent_ranks.length) && <small>Opponent context unavailable</small>}
  </div>
  return <section className="player-props" aria-label="Player props">
    {loading && !data && <p role="status">Loading saved player props…</p>}{error && <p role="alert">{error}</p>}
    {refreshing && <p className="source-note" role="status">Refreshing sources · Saved props remain visible.</p>}
    {(rankings.error || positions.error) && <p role="status">Some opponent context could not be updated. {rankings.error || positions.error}</p>}
    {data && <>
      <div className="prop-toolbar"><Dropdown label="Prop statistic" value={categoryValue} onChange={value => { setCategory(value); setSelected('') }}
        options={[...data.categories.map(category => ({ value: category.key, label: category.label })), { value: 'all', label: 'All supported statistics' }]} />
        <div className="segmented" aria-label="Filter players by team">{['all', ...teams].map(team => <button key={team} aria-pressed={teamFilter === team} onClick={() => setTeamFilter(team)}>{team === 'all' ? 'Both teams' : team}</button>)}</div></div>
      {data.sources.some(source => source.error) && <p role="status">A source refresh failed. Saved quotes or player data may be out of date.</p>}
      {!groups.length && <p className="empty-state">No verified props for this selection. Check source status and matching notices below.</p>}
      <div className="prop-grid">{groups.map(item => <article className="prop-card" style={teamStyle(item.player.team)} key={item.key}>
        <button className="player-heading" onClick={() => { setSelected(item.key); setInspection(null) }}>
          {teamLogos[item.player.team] && <img src={teamLogos[item.player.team]!} alt="" width="32" height="32" />}
          <span>{item.player.name}<small>{item.player.team} · {item.player.position}</small></span></button>
        <div className="prop-market"><div><small>{item.label}</small>{thresholdPicker(item)}</div><div className="prop-ask"><small>Yes ask</small><strong>{askPrice(selectedMarket(item)?.yes_ask_dollars)}</strong></div></div>
        {context(item)}
        <button className="prop-log-button" onClick={() => { setSelected(item.key); setInspection(null) }}>Game log <span aria-hidden="true">↗</span></button>
      </article>)}</div>
      <p className="source-note">Saved Yes ask prices before fees. Choose a threshold, then open a player’s log. Position ranks cover the entire position group.</p>
      <Sources sources={data.sources} />
      {(rankings.data?.sources.some(source => source.error) || positions.data?.sources.some(source => source.error)) && <p role="status">Opponent ranking data has a refresh error. Inspect source timestamps in the team logs.</p>}
      <details className="provenance"><summary>Matching & coverage notices ({data.issues.length + data.warnings.length})</summary>
        {data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}<ul>{data.issues.map((issue, index) => <li key={index}>{issue.market}: {issue.reason}</li>)}</ul></details>
      {!!data.unsupported.length && <details className="provenance"><summary>Other linked markets · not yet supported ({data.unsupported.length} series)</summary>
        <p>Quotes and logs for these market types are not implemented. Linked events do not guarantee open contracts.</p>
        <ul>{data.unsupported.map(item => <li key={item.series}>{item.label}<small className="metric-note">{item.events.join(', ')}</small></li>)}</ul></details>}
    </>}
    {(group || inspection) && <Modal title={inspection ? `${inspection.team} · Opponent game log` : `${group!.player.name} · ${group!.label}`} onClose={() => { setSelected(''); setInspection(null) }}>
      {inspection ? <>
        {group && <button className="back-link" onClick={() => setInspection(null)}>← Back to {group.player.name}</button>}
        {inspection.kind === 'position'
          ? <PositionDefenseView embedded key={`${inspection.team}:${inspection.category}`} season={season} revision={revision} refreshing={refreshing} teamCodes={[inspection.team]} categoryKeys={[inspection.category]} initialCategory={inspection.category} />
          : <RankingInspection season={season} revision={revision} teamCode={inspection.team} category={inspection.category} />}
      </> : group && <>
        <div className="log-context">{thresholdPicker(group)}<strong>{askPrice(market?.yes_ask_dollars)} <small>Yes ask · before fees</small></strong></div>
        <PlayerLog group={group} season={season} revision={revision} threshold={market?.threshold} onInspect={setInspection} />
        {market && <><details className="provenance"><summary>Contract & settlement rules</summary><p>{market.title}</p><p>{market.rules}</p><p className="settlement-rules">{market.rules_secondary}</p><small>{market.ticker}</small></details>
          <button onClick={() => onRecord({ description: market.title, selection: '', market_ticker: market.ticker, game_id: gameId })}>Record a bet on this prop</button></>}
      </>}
    </Modal>}
  </section>
}
