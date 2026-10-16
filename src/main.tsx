import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { RankingsView } from './RankingsView'
import { MatchupsView } from './MatchupsView'
import { PositionDefenseView } from './PositionDefenseView'
import { TrackerView } from './TrackerView'
import type { BetSelection, PendingSelection } from './TrackerView'
import { navigate, useHash } from './ui'
import { InstallApp } from './InstallApp'

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
  // Visible and editable until season rollover rules are agreed.
  const [season, setSeason] = useState(String(new Date().getFullYear()))
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const hash = useHash()
  const view = ['rankings', 'sources', 'tracker'].includes(hash) ? hash : 'matchups'
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
    void request<{ sources: Source[] }>(`/api/sources?season=${season}`, { signal: controller.signal })
      .then(data => {
        if (disposed) return
        setSources(data.sources)
        if (!autoOpened.current.has(season)) {
          autoOpened.current.add(season)
          void refresh(data.sources)
        }
      })
      .catch(() => {
        if (!disposed) setError('Unable to load saved data. Make sure Kalshi Deck is running, then reload this page.')
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
  }, [season, validSeason])

  async function refresh(selected: Source[]) {
    if (refreshLock.current) return
    refreshLock.current = true
    setError('')
    try {
      for (const source of selected) {
        setRefreshing(source.name)
        try {
          const updated = await request<Source>(`/api/sources/${source.name}/refresh?season=${season}`, { method: 'POST' })
          setSources(current => current.map(item => item.name === updated.name ? updated : item))
        } catch {
          setError(`Could not confirm the refresh of ${source.label}. Reload to check the saved status.`)
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
    setPendingSelection({ id: crypto.randomUUID(), leg })
    navigate('tracker')
  }

  return (
    <div className="app-shell">
      <header className="app-header"><button className="brand" onClick={() => navigate('games')}><span className="brand-mark" aria-hidden="true">K</span>Kalshi Deck</button>
        <nav className="app-nav" aria-label="Research views">
          <button aria-current={view === 'matchups' ? 'page' : undefined} onClick={() => navigate('games')}>Games</button>
          <button aria-current={view === 'rankings' ? 'page' : undefined} onClick={() => navigate('rankings')}>Rankings</button>
          <button aria-current={view === 'tracker' ? 'page' : undefined} onClick={() => navigate('tracker')}>Bet tracker</button>
          <button aria-current={view === 'sources' ? 'page' : undefined} onClick={() => navigate('sources')}>Data</button>
        </nav>
        <div className="app-actions"><label htmlFor="season" className="season-label">Season <input id="season" inputMode="numeric" value={season} disabled={refreshing !== null}
          onChange={event => { setSeason(event.target.value); navigate('games', true) }} aria-describedby="season-note" /></label>
          <button disabled={loading || refreshing !== null || !validSeason || sources.length === 0} onClick={() => void refresh(sources)}>
            {refreshing ? 'Refreshing…' : '↻ Refresh'}</button></div>
      </header>
      <main className="app-main">
        <span id="season-note" className="sr-only">NFL season for saved statistics and game identities. Current markets and injury reports may cover a different period.</span>
        <div className="refresh-status" role="status" aria-live="polite">{loading ? 'Loading saved source status…' : refreshing
          ? `Refreshing ${sources.find(source => source.name === refreshing)?.label ?? 'sources'} · Saved data remains visible`
          : sources.some(source => source.status === 'refresh_failed') ? 'Some updates failed · Saved data retained. See Data for details.' : sources.length ? 'Saved snapshots ready · Refresh on open' : ''}</div>
        {!validSeason && <p role="alert">Enter a four-digit NFL season between 1999 and 2100.</p>}
        {error && <p role="alert">{error}</p>}
        <div hidden={view !== 'matchups'}>{validSeason && <MatchupsView key={season} season={season} revision={revision} refreshing={refreshing !== null} onRecord={recordSelection} />}</div>
        <TrackerView visible={view === 'tracker'} pending={pendingSelection} consumePending={() => setPendingSelection(null)} />
        {validSeason && view === 'rankings' && <div className="research-page"><RankingsView key={season} season={season} revision={revision} refreshing={refreshing !== null} />
          <details className="research-expand"><summary>Defense by player position</summary><PositionDefenseView key={`position-${season}`} season={season} revision={revision} refreshing={refreshing !== null} /></details></div>}
      <div hidden={view !== 'sources'}><InstallApp /></div>
      {view === 'sources' && <div className="research-page"><h1>Data sources</h1>
      <p className="source-note">Season applies to nflverse data and game identities. Markets, coverage and injury reports use current published data. Sources refresh once on opening; spread lines load automatically when shown. No background polling.</p>
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
  <StrictMode><App /></StrictMode>,
)

// Register only in the built app; Vite development should remain independent.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).catch(error => {
      console.warn('Kalshi Deck recovery page could not be registered.', error)
    })
  })
}
