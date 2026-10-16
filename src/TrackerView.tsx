import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

export type BetSelection = { description: string; selection: string; market_ticker: string; game_id: string }
export type PendingSelection = { id: string; leg: BetSelection; notes?: string }
type Units = { display: string; exact: string; rounded: boolean }
type TicketData = {
  title: string; kind: 'single' | 'combo'; placed_at: string; cost: string; unit_size: string
  potential_payout: string | null; returned: string | null; closed_at: string | null; notes: string; legs: BetSelection[]
}
type Ticket = TicketData & {
  id: string; revision: number; created_at: string; updated_at: string; status: 'open' | 'closed'
  stake_units: Units; profit: string | null; profit_units: Units | null
}
type Report = {
  default_unit_size: string | null; tickets: Ticket[]
  totals: { open_count: number; closed_count: number; open_cost: string; open_units: Units; profit: string; profit_units: Units }
}
type Draft = { id: string; revision: number | null; data: TicketData; closed: boolean }
const blankLeg = (): BetSelection => ({ description: '', selection: '', market_ticker: '', game_id: '' })
function newDraft(unit: string | null, leg?: BetSelection, notes = ''): Draft {
  return { id: crypto.randomUUID(), revision: null, closed: false, data: {
    title: leg?.description ?? '', kind: 'single', placed_at: new Date().toISOString(), cost: '', unit_size: unit ?? '',
    potential_payout: null, returned: null, closed_at: null, notes, legs: [leg ? { ...leg } : blankLeg()],
  } }
}
function editDraft(ticket: Ticket, close = false): Draft {
  const { title, kind, placed_at, cost, unit_size, potential_payout, returned, closed_at, notes, legs } = ticket
  return { id: ticket.id, revision: ticket.revision, closed: close || ticket.status === 'closed', data: {
    title, kind, placed_at, cost, unit_size, potential_payout, returned,
    closed_at: close && !closed_at ? new Date().toISOString() : closed_at, notes, legs: legs.map(leg => ({ ...leg })),
  } }
}
function dollars(value: string | null) {
  if (value === null) return '—'
  const negative = value.startsWith('-')
  const [whole, fraction = ''] = value.replace(/^-/, '').split('.')
  return `${negative ? '−' : ''}$${whole}.${fraction.padEnd(2, '0')}`
}
function UnitValue({ value }: { value: Units | null }) {
  return value === null ? <>—</> : <span title={`Exact units: ${value.exact}`}>
    {value.rounded ? '≈ ' : ''}{value.display}u
  </span>
}
function localDate(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
function isoDate(value: string) {
  return value ? new Date(value).toISOString() : ''
}
async function request<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method, cache: 'no-store', ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  const result: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = result && typeof result === 'object' && 'detail' in result ? result.detail : null
    throw new Error(typeof detail === 'string' ? detail : `Tracker request failed (HTTP ${response.status}).`)
  }
  return result as T
}
function AmountInput({ label, value, onChange, required = false, disabled = false }: {
  label: string; value: string; onChange: (value: string) => void; required?: boolean; disabled?: boolean
}) {
  return <label>{label}<input inputMode="decimal" value={value} onChange={event => onChange(event.target.value)}
    required={required} disabled={disabled} pattern="[0-9]+(\.[0-9]+)?" maxLength={31} title="Enter dollars as decimal text, for example 9.99" /></label>
}

export function TrackerView({ visible, pending, consumePending }: {
  visible: boolean; pending: PendingSelection | null; consumePending: () => void
}) {
  const [report, setReport] = useState<Report | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [unitInput, setUnitInput] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [backup, setBackup] = useState<{ name: string; data: unknown; count: number | null } | null>(null)
  const mutationLock = useRef(false)
  const fileSelection = useRef(0)
  useEffect(() => {
    if (!visible || report) return
    let disposed = false
    void request<Report>('/api/tracker')
      .then(result => { if (!disposed) { setReport(result); setUnitInput(result.default_unit_size ?? ''); setError('') } })
      .catch((cause: unknown) => { if (!disposed) setError(cause instanceof Error ? cause.message : 'Tracker unavailable.') })
    return () => { disposed = true }
  }, [visible, report])

  async function reload(updateUnit = false) {
    const result = await request<Report>('/api/tracker')
    setReport(result)
    if (updateUnit) setUnitInput(result.default_unit_size ?? '')
  }
  async function mutate(action: () => Promise<void>) {
    if (mutationLock.current) return
    mutationLock.current = true; setBusy(true); setError(''); setMessage('')
    try { await action() }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not confirm the save. Keep your entries and reload the list before retrying.') }
    finally { mutationLock.current = false; setBusy(false) }
  }
  function replaceDraft(next: Draft | null) {
    if (draft && !window.confirm('Discard the current unsaved ticket form? Saved tickets will be kept.')) return false
    setDraft(next); setError(''); setMessage(''); return true
  }
  function update(values: Partial<TicketData>) {
    setDraft(current => current ? { ...current, data: { ...current.data, ...values } } : current)
  }
  function setLeg(index: number, values: Partial<BetSelection>) {
    if (draft) update({ legs: draft.data.legs.map((leg, i) => i === index ? { ...leg, ...values } : leg) })
  }
  async function saveTicket(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    const saving = draft
    await mutate(async () => {
      const saved = await request<Ticket>(`/api/tracker/tickets/${saving.id}`, 'PUT', {
        revision: saving.revision, ticket: { ...saving.data,
          returned: saving.closed ? saving.data.returned : null,
          closed_at: saving.closed ? saving.data.closed_at : null },
      })
      setDraft(null)
      setMessage(`${saved.title} saved. ${saved.status === 'closed' ? `Realized result: ${dollars(saved.profit)}.` : 'Ticket remains open.'}`)
      await reload()
    })
  }
  async function chooseBackup(file?: File) {
    const selection = ++fileSelection.current
    setBackup(null); setError('')
    if (!file) return
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error('Choose a tracker backup of at most 10 MB.')
      const data: unknown = JSON.parse(await file.text())
      if (!data || typeof data !== 'object' || !('tickets' in data) || !Array.isArray(data.tickets)) throw new Error('This file does not contain a ticket list.')
      if (selection === fileSelection.current) setBackup({ name: file.name, data, count: data.tickets.length })
    } catch (cause) { if (selection === fileSelection.current) setError(cause instanceof Error ? cause.message : 'Unable to read backup.') }
  }
  const tickets = report?.tickets.filter(ticket => (filter === 'all' || ticket.status === filter)
    && [ticket.title, ticket.notes, ...ticket.legs.flatMap(leg => [leg.description, leg.selection, leg.market_ticker])]
      .some(text => text.toLowerCase().includes(query.toLowerCase()))) ?? []

  return <section hidden={!visible} aria-labelledby="tracker-title" className="tracker">
    <h2 id="tracker-title">Bet tracker</h2>
    <p>Record bets placed on Kalshi. Entries stay here across seasons. Money amounts are USD; payout and return include your stake.</p>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {!report && !error && <p role="status">Loading saved tickets…</p>}
    <div className="controls">
      <button disabled={busy} onClick={() => void mutate(() => reload(true))}>Reload saved tickets</button>
      <button disabled={busy || !report} onClick={() => replaceDraft(newDraft(report?.default_unit_size ?? null))}>Record a bet</button>
    </div>
    {report && <>
      <dl className="tracker-totals">
        <div><dt>Realized profit / loss</dt><dd>{dollars(report.totals.profit)}</dd><dd><UnitValue value={report.totals.profit_units} /></dd></div>
        <div><dt>Open stake</dt><dd>{dollars(report.totals.open_cost)}</dd><dd><UnitValue value={report.totals.open_units} /></dd></div>
        <div><dt>Tickets</dt><dd>{report.totals.open_count} open · {report.totals.closed_count} closed</dd></div>
      </dl>
      <p className="source-note">Realized results include closed tickets only. Units use each ticket’s original unit size; ≈ marks a rounded display. Calculations retain full precision.</p>
      <form className="tracker-unit-form" onSubmit={event => {
        event.preventDefault(); void mutate(async () => {
          await request('/api/tracker/settings', 'PUT', { default_unit_size: unitInput })
          await reload(true); setMessage('Default unit size saved. Existing tickets and open forms keep their original unit size.')
        })
      }}>
        <AmountInput label="Default unit size ($)" value={unitInput} onChange={setUnitInput} required disabled={busy} />
        <button disabled={busy}>Save default</button>
      </form>
      {!report.default_unit_size && <p className="source-note">Set your usual unit size, or enter the original unit size directly when recording a bet.</p>}

      {pending && <aside className="pending-bet">
        <p><strong>Selection to record:</strong> {pending.leg.description}{pending.leg.selection && ` · ${pending.leg.selection}`}</p>
        {pending.notes && <p className="settlement-rules">{pending.notes}</p>}
        <div className="controls">
          <button disabled={busy} onClick={() => {
            if (replaceDraft(newDraft(report.default_unit_size, pending.leg, pending.notes))) consumePending()
          }}>Start a ticket with this selection</button>
          {draft && <button disabled={busy} onClick={() => {
            const notes = [draft.data.notes, pending.notes ? `${pending.leg.description}:\n${pending.notes}` : ''].filter(Boolean).join('\n\n')
            if (notes.length > 10000) { setError('Combined notes exceed 10,000 characters. Shorten the ticket notes before adding this selection.'); return }
            update({ kind: 'combo', legs: [...draft.data.legs, { ...pending.leg }], notes }); consumePending()
          }}>Add as a combo leg to this form</button>}
          <button disabled={busy} onClick={consumePending}>Dismiss selection</button>
        </div>
      </aside>}

      {draft && <form className="ticket-form" onSubmit={event => void saveTicket(event)}>
        <h3>{draft.revision === null ? 'Record a ticket' : 'Edit / close ticket'}</h3>
        <fieldset disabled={busy}>
          <legend>Ticket details</legend>
          <label>Description<input value={draft.data.title} required maxLength={240} onChange={event => update({ title: event.target.value })} /></label>
          <div className="tracker-fields">
            <label>Ticket type<select value={draft.data.kind} onChange={event => {
              const kind = event.target.value as 'single' | 'combo'
              if (kind === 'single' && draft.data.legs.length > 1) {
                setError('Remove extra legs before changing this ticket to a single.'); return
              }
              update({ kind, legs: kind === 'combo' && draft.data.legs.length < 2 ? [...draft.data.legs, blankLeg()] : draft.data.legs })
            }}><option value="single">Single</option><option value="combo">Combo / parlay</option></select></label>
            <label>Placed at (local time)<input type="datetime-local" required value={localDate(draft.data.placed_at)} onChange={event => update({ placed_at: isoDate(event.target.value) })} /></label>
          </div>
          {draft.data.legs.map((leg, index) => <fieldset key={index} className="ticket-leg">
            <legend>{draft.data.kind === 'combo' ? `Leg ${index + 1}` : 'Selection'}</legend>
            <label>Market / selection description<input required maxLength={500} value={leg.description} onChange={event => setLeg(index, { description: event.target.value })} /></label>
            <label>Chosen side / outcome<input required maxLength={120} placeholder="For example: Yes, No, or the chosen outcome" value={leg.selection} onChange={event => setLeg(index, { selection: event.target.value })} /></label>
            <details><summary>Optional market reference</summary>
              <label>Kalshi market ticker<input maxLength={240} value={leg.market_ticker} onChange={event => setLeg(index, { market_ticker: event.target.value })} /></label>
              <label>Game reference<input maxLength={120} value={leg.game_id} onChange={event => setLeg(index, { game_id: event.target.value })} /></label>
            </details>
            {draft.data.kind === 'combo' && <button type="button" onClick={() => update({ legs: draft.data.legs.filter((_, i) => i !== index) })}>Remove leg {index + 1}</button>}
          </fieldset>)}
          {draft.data.kind === 'combo' && <button type="button" disabled={draft.data.legs.length >= 100} onClick={() => update({ legs: [...draft.data.legs, blankLeg()] })}>Add a leg</button>}
          <p className="source-note">You can manually record markets not shown in the research views. For a combo, enter one total cost and payout for the whole ticket.</p>
          <div className="tracker-fields">
            <AmountInput label="Actual total cost, including fees ($)" value={draft.data.cost} required onChange={cost => update({ cost })} />
            <AmountInput label="Original unit size ($)" value={draft.data.unit_size} required disabled={draft.revision !== null} onChange={unit_size => update({ unit_size })} />
            <AmountInput label="Potential total payout ($, optional)" value={draft.data.potential_payout ?? ''} onChange={value => update({ potential_payout: value || null })} />
          </div>
          {draft.revision !== null && <p className="source-note">This saved ticket retains its original unit size.</p>}
          <label>Status<select value={draft.closed ? 'closed' : 'open'} onChange={event => {
            const closed = event.target.value === 'closed'
            setDraft({ ...draft, closed, data: { ...draft.data, closed_at: closed ? draft.data.closed_at || new Date().toISOString() : null,
              returned: closed ? draft.data.returned : null } })
          }}><option value="open">Open · still holding the bet</option><option value="closed">Closed · entirely sold or settled</option></select></label>
          {draft.closed && <div className="tracker-fields">
            <AmountInput label="Actual total returned, after fees ($)" value={draft.data.returned ?? ''} required onChange={value => update({ returned: value || null })} />
            <label>Closed at (local time)<input type="datetime-local" required value={localDate(draft.data.closed_at)} onChange={event => update({ closed_at: isoDate(event.target.value) || null })} /></label>
          </div>}
          <label>Notes (optional)<textarea maxLength={10000} rows={3} value={draft.data.notes} onChange={event => update({ notes: event.target.value })} /></label>
          <div className="controls"><button>{busy ? 'Saving…' : 'Save ticket'}</button><button type="button" onClick={() => replaceDraft(null)}>Cancel form</button></div>
        </fieldset>
      </form>}

      <h3>Saved tickets</h3>
      <div className="controls">
        <label>Show <select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All</option><option value="open">Open</option><option value="closed">Closed</option></select></label>
        <label>Search <input type="search" value={query} onChange={event => setQuery(event.target.value)} /></label>
      </div>
      {!tickets.length && <p>No saved tickets match this view.</p>}
      {tickets.map(ticket => <article key={ticket.id} className="saved-ticket">
        <div className="source-heading"><h3>{ticket.title}</h3><span>{ticket.kind === 'combo' ? `${ticket.legs.length}-leg combo` : 'Single'} · {ticket.status}</span></div>
        <p className="source-note">Placed {new Date(ticket.placed_at).toLocaleString()}{ticket.closed_at && ` · Closed ${new Date(ticket.closed_at).toLocaleString()}`}</p>
        <dl className="tracker-totals">
          <div><dt>Cost</dt><dd>{dollars(ticket.cost)} · <UnitValue value={ticket.stake_units} /></dd></div>
          <div><dt>Original unit</dt><dd>{dollars(ticket.unit_size)}</dd></div>
          <div><dt>Potential payout</dt><dd>{dollars(ticket.potential_payout)}</dd></div>
          <div><dt>Total returned</dt><dd>{dollars(ticket.returned)}</dd></div>
          <div><dt>Realized profit / loss</dt><dd>{dollars(ticket.profit)} · <UnitValue value={ticket.profit_units} /></dd></div>
        </dl>
        <details><summary>Selections and notes</summary><ol>{ticket.legs.map((leg, index) => <li key={index}>
          {leg.description} · <strong>{leg.selection}</strong>
          {(leg.market_ticker || leg.game_id) && <small className="metric-note">{[leg.market_ticker, leg.game_id].filter(Boolean).join(' · ')}</small>}
        </li>)}</ol>{ticket.notes && <p className="settlement-rules">{ticket.notes}</p>}</details>
        <div className="controls">
          <button disabled={busy} onClick={() => replaceDraft(editDraft(ticket))}>Edit ticket</button>
          {ticket.status === 'open' && <button disabled={busy} onClick={() => replaceDraft(editDraft(ticket, true))}>Close ticket</button>}
        </div>
      </article>)}

      <details className="tracker-backups"><summary>Export / import backups</summary>
        <p>Export saves all tickets and the default unit size. Import adds missing tickets and skips identical ones. Conflicting tickets stop the import without changing saved records. An existing default unit size is kept.</p>
        <p><a href="/api/tracker/export" download="kalshi-deck-tracker.json">Download tracker backup</a></p>
        <label>Select a tracker backup<input type="file" accept=".json,application/json" disabled={busy} onChange={event => void chooseBackup(event.target.files?.[0])} /></label>
        {backup && <><p>{backup.name} · {backup.count} tickets in file. The full file will be validated before saving.</p>
          <button disabled={busy} onClick={() => void mutate(async () => {
            const result = await request<{ added: number; skipped: number; kept_current_unit_size: boolean }>('/api/tracker/import', 'POST', backup.data)
            setBackup(null); await reload(true)
            setMessage(`Import complete: ${result.added} added, ${result.skipped} already present.${result.kept_current_unit_size ? ' Your current default unit size was kept.' : ''}`)
          })}>Import this backup</button>
        </>}
      </details>
    </>}
  </section>
}
