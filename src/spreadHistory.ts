export type HistoryPoint = { timestamp: number; midpoint: number | null; bid: string | null; ask: string | null }
export type HistoryData = {
  points: HistoryPoint[]; fetched_at: string; url: string
  context: { ticker: string; series: string; start_ts: number; end_ts: number; interval_minutes: number }
}
export type HistoryEntry = {
  data?: HistoryData; error?: string; attemptedAt?: string; status?: 'queued' | 'loading'
}

// Session memory only: navigation reuses data, page reload starts fresh.
let entries: Readonly<Record<string, HistoryEntry>> = {}
const listeners = new Set<() => void>()
let queue = Promise.resolve()
export const historySnapshot = () => entries
export function subscribeHistory(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

// Mounting a card (including StrictMode/remounts) gets one automatic attempt per
// contract per session. Explicit refresh can retry failures or update saved data.
export function ensureSpreadHistory(tickers: string[]) {
  return loadSpreadHistory(tickers.filter(ticker => !entries[ticker]))
}
function update(ticker: string, entry: HistoryEntry) {
  entries = { ...entries, [ticker]: entry }
  listeners.forEach(listener => listener())
}

export function loadSpreadHistory(tickers: string[]) {
  const end = Math.floor(Date.now() / 1000)
  const start = end - 7 * 86400
  for (const ticker of new Set(tickers)) {
    if (entries[ticker]?.status) continue
    update(ticker, { ...entries[ticker], error: undefined, status: 'queued' })
    queue = queue.then(async () => {
      const attemptedAt = new Date().toISOString()
      update(ticker, { ...entries[ticker], status: 'loading', attemptedAt })
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 35000)
      try {
        const series = ticker.split('-')[0]
        if (!['KXNFLSPREAD', 'KXNCAAFSPREAD'].includes(series)) throw new Error('Unsupported spread history series.')
        const response = await fetch(`/api/markets/${series}/${encodeURIComponent(ticker)}/history?start=${start}&end=${end}&interval=60`, { signal: controller.signal })
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(typeof body?.detail === 'string' ? body.detail : `History unavailable (HTTP ${response.status}).`)
        }
        const data = await response.json() as HistoryData
        if (data.context.ticker !== ticker || data.context.series !== series || data.context.start_ts !== start || data.context.end_ts !== end
          || data.context.interval_minutes !== 60 || !Array.isArray(data.points)
          || data.points.some(point => !Number.isInteger(point.timestamp) || point.timestamp % 3600 !== 0
            || point.timestamp < start || point.timestamp > end
            || (point.midpoint !== null && (!Number.isFinite(point.midpoint) || point.midpoint <= 0 || point.midpoint >= 1)))) {
          throw new Error('History response does not match the requested contract or window.')
        }
        update(ticker, { data, attemptedAt })
      } catch (cause: unknown) {
        update(ticker, { data: entries[ticker]?.data, attemptedAt,
          error: cause instanceof Error && cause.name !== 'AbortError' ? cause.message : 'History request timed out. Try refreshing again.' })
      } finally {
        clearTimeout(timeout)
      }
    })
  }
  return queue
}

export function historyWindow(data: HistoryData, hours: number): HistoryPoint[] {
  const end = data.context.end_ts
  const start = Math.max(data.context.start_ts, end - hours * 3600)
  const points = new Map(data.points.map(point => [point.timestamp, point]))
  const slots: HistoryPoint[] = []
  for (let timestamp = Math.ceil(start / 3600) * 3600; timestamp <= end; timestamp += 3600) {
    slots.push(points.get(timestamp) ?? { timestamp, midpoint: null, bid: null, ask: null })
  }
  return slots
}

export function historyPath(points: HistoryPoint[], start: number, end: number, width = 480) {
  let connected = false
  return points.map(point => {
    if (point.midpoint === null) { connected = false; return '' }
    const command = connected ? 'L' : 'M'
    connected = true
    return `${command}${historyX(point.timestamp, start, end, width)},${historyY(point.midpoint)}`
  }).join(' ')
}
export const historyX = (timestamp: number, start: number, end: number, width = 480) => 44 + (timestamp - start) / (end - start) * (width - 60)
export const historyY = (midpoint: number) => 16 + (1 - midpoint) * 140
