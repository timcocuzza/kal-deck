import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { RankingsView } from './RankingsView'
import { MatchupsView } from './MatchupsView'
import { PositionDefenseView } from './PositionDefenseView'
import { TrackerView } from './TrackerView'
import type { BetSelection, PendingSelection } from './TrackerView'
import { navigate, useHash } from './ui'
import { WatchlistProvider, WatchlistStatus, WatchlistView, useWatchlist } from './Watchlist'
import { InstallApp } from './InstallApp'
import { CollegeView } from './CollegeView'

type Source = {
  name: string
  label: string
  provider: string
  season: number | null
  status: 'not_loaded' | 'ready' | 'refresh_failed'
  fetched_at: string | null
  source_updated_at?: string | null
  attempted_at: string | null
  error: string | null
  url?: string
  warnings?: string[]
  context?: { season?: number; week?: number }
}

function dateLabel(value: string | null | undefined) {
  if (!value) return 'Not supplied'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) throw new Error(`Local service returned HTTP ${response.status}.`)
  return response.json() as Promise<T>
}

function App() {
  const watchlist = useWatchlist()
  // Default to the current year; saved watchlist games retain their season.
  const [season, setSeason] = useState(String(new Date().getFullYear()))
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const hash = useHash()
  const [researchSport, setResearchSport] = useState<'nfl' | 'cfb'>('nfl')
  const sharedView = hash === 'watchlist' || hash === 'tracker'
  const sport = sharedView ? researchSport : hash.startsWith('cfb') ? 'cfb' : 'nfl'
  const view = sharedView ? hash : hash === 'cfb/sources' ? 'sources' : sport === 'cfb' ? 'college' : ['rankings', 'sources'].includes(hash) ? hash : 'matchups'
  useEffect(() => { if (!sharedView) setResearchSport(sport) }, [sport, sharedView])
  const scope = `${sport}:${season}`
  const activeScope = useRef(scope)
  activeScope.current = scope
  const autoOpened = useRef(new Set<string>())
  const [pendingSelection, setPendingSelection] = useState<PendingSelection | null>(null)
  const refreshLock = useRef(false)
  const validSeason = /^\d{4}$/.test(season) && Number(season) >= 1999 && Number(season) <= 2100

  useEffect(() => {
    setSources([])
    if (!validSeason) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 5000)
    setLoading(true)
    setError('')
    void request<{ sources: Source[] }>(`/api/sources?season=${season}&sport=${sport}`, { signal: controller.signal })
      .then(data => {
        if (disposed) return
        setSources(data.sources)
      })
      .catch(() => {
        if (!disposed) setError('Unable to load saved data. Make sure Deck is running, then reload this page.')
      })
      .finally(() => {
        window.clearTimeout(timeout)
        if (!disposed) setLoading(false)
      })
    let disposed = false
    return () => {
      disposed = true
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [season, sport, validSeason])

  useEffect(() => {
    if (loading || !validSeason || !sources.length || refreshLock.current || autoOpened.current.has(scope)) return
    if (sources.some(source => source.name.startsWith('cfb_') !== (sport === 'cfb'))) return
    autoOpened.current.add(scope)
    void refresh(sources)
  }, [loading, validSeason, sources, scope, refreshing])

  async function refresh(selected: Source[]) {
    if (refreshLock.current) return
    refreshLock.current = true
    setError('')
    try {
      for (const source of selected) {
        if (activeScope.current !== scope) {
          autoOpened.current.delete(scope)
          break
        }
        setRefreshing(source.name)
        try {
          const updated = await request<Source>(`/api/sources/${source.name}/refresh?season=${season}`, { method: 'POST' })
          if (activeScope.current === scope) setSources(current => current.map(item => item.name === updated.name ? updated : item))
        } catch {
          if (activeScope.current === scope) setError(`Could not confirm the refresh of ${source.label}. Reload to check the saved status.`)
          // Continue other independent sources; saved snapshots remain intact.
        }
      }
    } finally {
      setRefreshing(null)
      refreshLock.current = false
      setRevision(value => value + 1)
    }
  }

  function recordSelection(leg: BetSelection) {
    const watched = watchlist.entries.find(entry => entry.ticker === leg.market_ticker && entry.game_id === leg.game_id)
    setPendingSelection({ id: crypto.randomUUID(), selections: [{ leg: { ...leg, selection: leg.selection || watched?.side || '' }, notes: watched?.notes ?? '' }] })
    navigate('tracker')
  }

  return (
    <div className="app-shell">
      <header className="app-header"><button className="brand" onClick={() => navigate(sport === 'cfb' ? 'cfb' : 'games')}><img className="brand-logo" src="/icons/deck-logo.webp" alt="Deck" width="112" height="40" /></button>
        <nav className="sport-nav segmented" aria-label="Sport">
          <button aria-pressed={sport === 'nfl'} onClick={() => navigate('games')}>NFL</button>
          <button aria-pressed={sport === 'cfb'} onClick={() => navigate('cfb')}>CFB</button>
        </nav>
        <nav className="app-nav" aria-label={`${sport === 'cfb' ? 'CFB' : 'NFL'} sections`}>
          {sport === 'cfb' ? <>
            <button aria-current={view === 'college' && hash.split('?')[0] !== 'cfb/ratings' ? 'page' : undefined} onClick={() => navigate('cfb')}>Games</button>
            <button aria-current={hash.split('?')[0] === 'cfb/ratings' ? 'page' : undefined} onClick={() => navigate('cfb/ratings')}>Ratings</button>
          </> : <>
          <button aria-current={view === 'matchups' ? 'page' : undefined} onClick={() => navigate('games')}>Games</button>
          <button aria-current={view === 'rankings' ? 'page' : undefined} onClick={() => navigate('rankings')}>Rankings</button>
          </>}
          <button aria-current={view === 'sources' ? 'page' : undefined} onClick={() => navigate(sport === 'cfb' ? 'cfb/sources' : 'sources')}>Data</button>
        </nav>
        <nav className="app-nav shared-nav" aria-label="Shared tools">
          <button aria-current={view === 'watchlist' ? 'page' : undefined} onClick={() => navigate('watchlist')}>Watchlist</button>
          <button aria-current={view === 'tracker' ? 'page' : undefined} onClick={() => navigate('tracker')}>Bet tracker</button>
        </nav>
        <div className="app-actions">
          <button disabled={loading || refreshing !== null || !validSeason || sources.length === 0} onClick={() => void refresh(sources)}>
            {refreshing ? 'Refreshing…' : '↻ Refresh'}</button></div>
      </header>
      <main className="app-main">
        <div className="refresh-status" role="status" aria-live="polite">{loading ? 'Loading saved source status…' : refreshing
          ? `Refreshing ${sources.find(source => source.name === refreshing)?.label ?? 'sources'} · Saved data remains visible`
          : sources.some(source => source.status === 'refresh_failed') ? 'Some updates failed · Saved data retained. See Data for details.' : sources.length ? 'Saved snapshots ready · Refresh on open' : ''}</div>
        {error && <p role="alert">{error}</p>}
        <WatchlistStatus />
        {view === 'watchlist' && <WatchlistView revision={revision} onRecord={recordSelection} onCombo={selections => {
          setPendingSelection({ id: crypto.randomUUID(), selections, autoStart: true })
          navigate('tracker')
        }} onOpen={entry => {
          setSeason(String(entry.season))
          if (entry.sport === 'cfb') {
            setResearchSport('cfb')
            navigate(`cfb/game/${entry.game_id}?week=${entry.week}&season_type=${entry.season_type ?? 'regular'}&market=${encodeURIComponent(entry.ticker)}`)
            return
          }
          setResearchSport('nfl')
          navigate(`game/${encodeURIComponent(entry.game_id)}?week=${entry.week}&tab=${entry.kind === 'prop' ? 'props' : 'stats'}&market=${encodeURIComponent(entry.ticker)}`)
        }} />}
        <div hidden={view !== 'matchups'}>{validSeason && sport === 'nfl' && <MatchupsView key={season} season={season} revision={revision} refreshing={refreshing !== null} onRecord={recordSelection} />}</div>
        {view === 'college' && validSeason && <CollegeView key={season} season={season} revision={revision} onSeason={setSeason} onRecord={recordSelection} />}
        <TrackerView visible={view === 'tracker'} pending={pendingSelection} consumePending={() => setPendingSelection(null)} />
        {validSeason && view === 'rankings' && <div className="research-page"><RankingsView key={season} season={season} revision={revision} refreshing={refreshing !== null} />
          <details className="research-expand"><summary>Defense by player position</summary><PositionDefenseView key={`position-${season}`} season={season} revision={revision} refreshing={refreshing !== null} /></details></div>}
      <div hidden={view !== 'sources'}><InstallApp /></div>
      {view === 'sources' && <div className="research-page"><h1>Data sources</h1>
      <p className="source-note">{sport === 'cfb' ? 'College statistics, current schedules, and verified spread identities have separate saved snapshots. Refresh failures retain previous data. Current results may still lack statistics; coverage is shown beside each metric. Spread histories load independently when displayed.' : 'Season applies to nflverse data and game identities. Markets, coverage and injury reports use current published data. Sources refresh once on opening; spread lines load automatically when shown. Watched contracts check quotes near kickoff and results afterward while Deck is running.'}</p>
      <ul className="sources">
        {sources.map(source => (
          <li key={source.name}>
            <div className="source-heading">
              <h2>{source.label}</h2>
              <button disabled={refreshing !== null} onClick={() => void refresh([source])}
                aria-label={`Refresh ${source.label}`}>Refresh</button>
            </div>
            <p>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.provider}</a> : source.provider}
              {source.season && ` · ${source.season} season`}
              {source.name === 'injuries' && source.context && ` · ${source.context.season}, week ${source.context.week}`}
            </p>
            <p>{source.status === 'not_loaded' ? 'Not downloaded yet.'
              : source.status === 'refresh_failed' ? source.fetched_at
                ? 'Refresh failed. Showing the previous saved snapshot.' : 'Unavailable. No saved snapshot.'
                : 'Snapshot saved.'}</p>
            {source.fetched_at && <p>Fetched: {dateLabel(source.fetched_at)}</p>}
            {source.fetched_at && <p>Source update date: {dateLabel(source.source_updated_at)}</p>}
            {source.error && <p role="alert">{source.error} Last attempt: {dateLabel(source.attempted_at)}</p>}
            {source.warnings?.map(warning => <p className="source-note" key={warning}>{warning}</p>)}
          </li>
        ))}
      </ul></div>}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><WatchlistProvider><App /></WatchlistProvider></StrictMode>,
)

// Register only in the built app; Vite development should remain independent.
if (import.meta.env.PROD && !window.deckDesktop && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).catch(error => {
      console.warn('Deck recovery page could not be registered.', error)
    })
  })
}
