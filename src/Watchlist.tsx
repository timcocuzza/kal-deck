import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useReport } from './useReport'
import { askPrice, Modal } from './ui'
import { teamStyle } from './teamColors'
import type { BetSelection } from './TrackerView'
import { ticketSelections } from './ticketSelections'
import type { NotedSelection } from './ticketSelections'

type WatchReference = { ticker: string; kind: 'prop' | 'spread'; season: number; week: number; game_id: string; label: string }
type WatchDetails = { side: '' | 'Yes' | 'No'; notes: string; revision: number }
export type WatchEntry = WatchReference & WatchDetails
type WatchState = {
  entries: WatchEntry[]; busy: boolean; ready: boolean; error: string; toggle: (entry: WatchReference) => void; reload: () => void
  drafts: Record<string, WatchDetails>; setDraft: (ticker: string, draft: WatchDetails | null) => void
  update: (ticker: string, details: WatchDetails) => Promise<boolean>
  openEditor: (ticker: string) => void
}
const WatchContext = createContext<WatchState | null>(null)
export const useWatchlist = () => useContext(WatchContext)!

async function request(url = '/api/watchlist', method = 'GET', body?: WatchReference | WatchDetails): Promise<WatchEntry[]> {
  const response = await fetch(url, { method, cache: 'no-store', signal: AbortSignal.timeout(15000), headers: { 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to update watchlist.')
  return data.entries
}

export function WatchlistProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<WatchEntry[]>([])
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState('')
  const [drafts, setDrafts] = useState<Record<string, WatchDetails>>({})
  function setDraft(ticker: string, draft: WatchDetails | null) {
    setDrafts(current => {
      const next = { ...current }
      if (draft) next[ticker] = draft
      else delete next[ticker]
      return next
    })
  }
  const lock = useRef(false)
  async function run(action: () => Promise<WatchEntry[]>) {
    if (lock.current) return false
    lock.current = true; setBusy(true); setError('')
    try { setEntries(await action()); setReady(true); return true }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Watchlist unavailable.'); return false }
    finally { lock.current = false; setBusy(false) }
  }
  const reload = () => { void run(() => request()) }
  useEffect(reload, [])
  const toggle = (entry: WatchReference) => {
    const { ticker, kind, season, week, game_id, label } = entry
    const removing = entries.some(item => item.ticker === ticker)
    void run(() => removing
      ? request(`/api/watchlist/${encodeURIComponent(ticker)}`, 'DELETE')
      : request('/api/watchlist', 'PUT', { ticker, kind, season, week, game_id, label }))
      .then(saved => {
        if (!saved) return
        setDraft(ticker, null)
        setEditing(removing ? '' : ticker)
      })
  }
  const update = (ticker: string, details: WatchDetails) => run(() => request(`/api/watchlist/${encodeURIComponent(ticker)}`, 'PATCH', details))
  const editingEntry = entries.find(entry => entry.ticker === editing)
  return <WatchContext.Provider value={{ entries, ready, busy, error, toggle, reload, drafts, setDraft, update, openEditor: setEditing }}>
    {children}
    {editingEntry && <WatchEditor entry={editingEntry} onClose={() => { if (!lock.current) setEditing('') }} />}
  </WatchContext.Provider>
}

export function WatchlistStatus() {
  const { error, reload, busy } = useWatchlist()
  return error ? <p role="alert">{error} <button disabled={busy} onClick={reload}>Reload watchlist</button></p> : null
}

export function WatchButton({ entry }: { entry: WatchReference }) {
  const { entries, ready, busy, toggle } = useWatchlist()
  const pinned = entries.some(item => item.ticker === entry.ticker)
  return <button className="watch-button" disabled={!ready || busy} aria-pressed={pinned}
    aria-label={`${pinned ? 'Remove from' : 'Add to'} watchlist: ${entry.label}`} onClick={() => toggle(entry)}>
    <span aria-hidden="true">{pinned ? '★' : '☆'}</span> {pinned ? 'Watching' : 'Watch'}
  </button>
}

function WatchEditor({ entry, onClose }: { entry: WatchEntry; onClose: () => void }) {
  const { busy, drafts, setDraft, update } = useWatchlist()
  const draft = drafts[entry.ticker] ?? { side: entry.side, notes: entry.notes, revision: entry.revision }
  const dirty = draft.side !== entry.side || draft.notes !== entry.notes
  const conflict = dirty && draft.revision !== entry.revision
  return <Modal title="Watchlist details" className="watch-dialog" closeLabel="Close watchlist editor" onClose={onClose}>
    <p className="watch-editor-label">{entry.label}</p>
    <WatchlistStatus />
    <form className="watch-details" aria-label={`Side and notes for ${entry.label}`} onSubmit={event => {
      event.preventDefault()
      if (busy || !dirty || conflict) return
      void update(entry.ticker, draft).then(saved => {
        if (saved) { setDraft(entry.ticker, null); onClose() }
      })
    }}>
      <label>Your side<select value={draft.side} disabled={busy} onChange={event => setDraft(entry.ticker, { ...draft, side: event.target.value as WatchDetails['side'] })}>
        <option value="">Not chosen</option><option value="Yes">Yes</option><option value="No">No</option>
      </select></label>
      <label className="watch-notes">Notes<textarea rows={5} maxLength={10000} value={draft.notes} disabled={busy}
        placeholder="Why you’re watching this bet…" onChange={event => setDraft(entry.ticker, { ...draft, notes: event.target.value })} /></label>
      <div className="watch-edit-actions"><button type="submit" disabled={busy || !dirty || conflict}>Save</button>
        {dirty && <button type="button" disabled={busy} onClick={() => setDraft(entry.ticker, null)}>Reset to saved</button>}
        <small role="status">{dirty ? 'Unsaved changes' : 'Saved'}</small>
        <button type="button" disabled={busy} onClick={onClose}>Close</button>
      </div>
      {conflict && <div className="watch-conflict" role="status"><p>This entry changed elsewhere. Your edits are still here.</p>
        <details><summary>Saved side and notes</summary><p>{entry.side || 'Side not chosen'}</p><p className="settlement-rules">{entry.notes || 'No notes'}</p></details>
        <button type="button" disabled={busy} onClick={() => setDraft(entry.ticker, { ...draft, revision: entry.revision })}>Keep my edits</button>
      </div>}
    </form>
    <p className="source-note">Closing keeps unsaved edits for this session. Save to keep them after a reload.</p>
  </Modal>
}

type QuoteReport = {
  kickoff?: string | null
  groups?: { category: string; label: string; player: { name: string; team: string; position: string }; markets: WatchMarket[] }[]
  games?: { game_id: string; kickoff: string | null; away: WatchTeam; home: WatchTeam; markets: WatchMarket[] }[]
  sources: { name: string; fetched_at: string | null; error: string | null }[]
}
type WatchMarket = { ticker: string; label: string; team?: string; yes_ask_dollars: string | null; no_ask_dollars: string | null }
type WatchTeam = { code: string; name: string; logo: string | null }
function WatchCard({ entry, revision, onOpen, onRecord, choosing, selected, onSelect }: {
  entry: WatchEntry; revision: number; onOpen: (entry: WatchEntry) => void; onRecord: (selection: BetSelection) => void
  choosing: boolean; selected: boolean; onSelect: () => void
}) {
  const { busy, drafts, openEditor, toggle } = useWatchlist()
  const draft = drafts[entry.ticker]
  const dirty = draft != null && (draft.side !== entry.side || draft.notes !== entry.notes)
  const matchupUrl = `/api/matchups?season=${entry.season}&week=${entry.week}`
  const matchups = useReport<QuoteReport>(matchupUrl, revision)
  const { data, error, loading } = useReport<QuoteReport>(entry.kind === 'prop'
    ? `/api/matchups/${encodeURIComponent(entry.game_id)}/props?season=${entry.season}`
    : matchupUrl, revision)
  const game = matchups.data?.games?.find(game => game.game_id === entry.game_id)
  const kickoff = entry.kind === 'prop' ? data?.kickoff : game?.kickoff
  const [clock, setClock] = useState(Date.now())
  useEffect(() => {
    if (!kickoff) return
    const remaining = new Date(kickoff).getTime() - Date.now()
    if (!Number.isFinite(remaining) || remaining <= 0) return
    const timer = window.setTimeout(() => setClock(Date.now()), Math.min(remaining + 10, 2147483647))
    return () => window.clearTimeout(timer)
  }, [kickoff, clock])
  const started = kickoff != null && new Date(kickoff).getTime() <= Math.max(clock, Date.now())
  const markets = entry.kind === 'prop' ? data?.groups?.flatMap(group => group.markets) : game?.markets
  const contract = markets?.find(market => market.ticker === entry.ticker)
  const market = !started ? contract : undefined
  const group = data?.groups?.find(group => group.markets.some(market => market.ticker === entry.ticker))
  const source = data?.sources.find(source => source.name === (entry.kind === 'spread' ? 'spreads' : group?.category))
  const teamCode = group?.player.team ?? contract?.team ?? ''
  const team = [game?.away, game?.home].find(team => team?.code === teamCode)
  const matchup = entry.game_id.split('_').slice(2).join(' vs ')
  const savedLabel = entry.label.split(' · ')
  const title = entry.kind === 'prop' ? group?.player.name ?? savedLabel[0] : team?.name ?? matchup
  const statistic = entry.kind === 'prop' ? group?.label ?? (savedLabel.slice(1, -1).join(' · ') || 'Player prop') : 'Spread'
  const threshold = contract?.label ?? (entry.kind === 'prop' ? savedLabel.at(-1) : entry.label)
  return <article className={`prop-card watch-card${selected ? ' combo-selected' : ''}`} style={teamStyle(teamCode)}>
    {choosing && <label className="watch-combo-pick"><input type="checkbox" checked={selected}
      disabled={busy || (!selected && (dirty || !entry.side))} onChange={onSelect} aria-label={`Include in combo: ${entry.label}`} />
      {dirty ? 'Save edits to include' : !entry.side ? 'Choose a side to include' : selected ? 'Selected for combo' : 'Include in combo'}
    </label>}
    <div className="watch-card-heading">
      <button className="player-heading" disabled={!market} onClick={() => onOpen(entry)} aria-label={`Open ${entry.label}`}>
        {team?.logo && <img src={team.logo} alt="" width="32" height="32" onError={event => { event.currentTarget.style.display = 'none' }} />}
        <span>{title}<small>{group ? `${group.player.team} · ${group.player.position}` : matchup}</small></span>
      </button>
      <button className="watch-remove" disabled={busy} onClick={() => toggle(entry)} aria-label={`Remove from watchlist: ${entry.label}`} title="Remove from watchlist">×</button>
    </div>
    <div className="prop-market">
      <div><small>{statistic}</small><button className="watch-threshold" disabled={!market} onClick={() => onOpen(entry)}>{threshold}</button></div>
      <div className="prop-ask"><small>{entry.side || 'Yes'} ask</small><strong>{loading && !data ? 'Loading…' : askPrice(entry.side === 'No' ? market?.no_ask_dollars : market?.yes_ask_dollars)}</strong></div>
    </div>
    <div className="opponent-context watch-context">
      <small>{matchup} · Week {entry.week} · {entry.season}</small>
      <div className="watch-side"><span>Your side</span><strong>{entry.side || 'Not chosen'}</strong></div>
      {entry.notes && <p className="watch-note-preview">{entry.notes}</p>}
      {dirty && <small className="watch-card-status">Unsaved edits</small>}
    </div>
    {error && <small className="watch-card-status" role="alert">{error} {market && 'Showing the previous quote.'}</small>}
    {!loading && !market && <small className="watch-card-status">{started ? 'Game started · pregame quote unavailable' : 'Contract unavailable'}</small>}
    {data?.sources.some(source => source.error) && <small className="watch-card-status">Refresh failed · saved data may be out of date</small>}
    {source?.fetched_at && <small className="watch-quote-time" title={`Quote snapshot: ${new Date(source.fetched_at).toLocaleString()}`}>
      Saved quote · {new Date(source.fetched_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
    </small>}
    <div className="watch-card-actions">
      <button className="prop-log-button" disabled={busy} onClick={() => openEditor(entry.ticker)} aria-label={`Edit side and notes: ${entry.label}`}>Edit details <span aria-hidden="true">↗</span></button>
      {!choosing && <button className="prop-log-button" disabled={busy || dirty || !entry.side} onClick={() => onRecord({
        description: entry.label, selection: entry.side, market_ticker: entry.ticker, game_id: entry.game_id,
      })}>Record a bet</button>}
    </div>
  </article>
}

export function WatchlistView({ revision, onOpen, onRecord, onCombo }: {
  revision: number; onOpen: (entry: WatchEntry) => void; onRecord: (selection: BetSelection) => void
  onCombo: (selections: NotedSelection[]) => void
}) {
  const { entries, ready, busy, drafts } = useWatchlist()
  const [choosing, setChoosing] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [comboError, setComboError] = useState('')
  const picks = entries.filter(entry => selected.includes(entry.ticker))
  const needsDetails = picks.some(entry => !entry.side || (drafts[entry.ticker]
    && (drafts[entry.ticker].side !== entry.side || drafts[entry.ticker].notes !== entry.notes)))
  return <section className="research-page" aria-label="Watchlist"><div className="page-heading"><div><h1>Watchlist</h1>
    <p>Your saved spreads and player props across games.</p></div>
    {!choosing && entries.length > 1 && <button disabled={busy} onClick={() => setChoosing(true)}>Build combo</button>}</div>
    {choosing && <div className="watch-combo-bar" role="region" aria-label="Build a combo">
      <span role="status">{picks.length ? `${picks.length} selected` : 'Select at least 2 picks'}</span>
      <div className="controls"><button disabled={busy || picks.length < 2 || picks.length > 100 || needsDetails} onClick={() => {
        const selections = picks.map(entry => ({ leg: {
          description: entry.label, selection: entry.side, market_ticker: entry.ticker, game_id: entry.game_id,
        }, notes: entry.notes }))
        try { ticketSelections(selections); setComboError(''); onCombo(selections) }
        catch (cause) { setComboError(cause instanceof Error ? cause.message : 'Unable to prepare combo.') }
      }}>Record combo</button>
        <button disabled={busy} onClick={() => { setChoosing(false); setSelected([]); setComboError('') }}>Cancel</button>
      </div>
      {needsDetails && <small>Save the side and notes for each selected pick.</small>}
      {picks.length > 100 && <small>Select at most 100 picks.</small>}
      {comboError && <p role="alert">{comboError}</p>}
    </div>}
    {!ready && busy && <p role="status">Loading watchlist…</p>}
    {ready && !entries.length && <p className="empty-state">Select Watch on a spread or player prop to keep it here.</p>}
    <div className="prop-grid watch-list">{entries.map(entry => <WatchCard key={entry.ticker} entry={entry} revision={revision} onOpen={onOpen} onRecord={onRecord}
      choosing={choosing} selected={selected.includes(entry.ticker)} onSelect={() => {
        setSelected(current => current.includes(entry.ticker) ? current.filter(ticker => ticker !== entry.ticker) : [...current, entry.ticker])
        setComboError('')
      }} />)}</div>
    {!!entries.length && <p className="source-note">Use Edit details to choose a side and write notes. Prices show the selected side’s saved ask before fees; Yes ask is shown until you choose. Unavailable contracts stay saved until you remove them.</p>}
  </section>
}
