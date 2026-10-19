export type WatchTracking = {
  kickoff?: string
  yes_ask?: { dollars: string; fetched_at: string }
  no_ask?: { dollars: string; fetched_at: string }
  result?: 'yes' | 'no' | 'scalar' | 'void'
  market_status?: string
  result_fetched_at?: string
  checked_at?: string
  error?: string | null
}

export function watchOutcome(side: '' | 'Yes' | 'No', tracking?: WatchTracking) {
  if (!tracking?.result) return null
  if (tracking.result === 'scalar' || tracking.result === 'void') return { tone: 'neutral', label: 'Void / non-binary result' }
  const result = tracking.result === 'yes' ? 'Yes' : 'No'
  if (!side) return { tone: 'neutral', label: `Resolved ${result} · no side chosen` }
  return { tone: side === result ? 'hit' : 'miss', label: `${side === result ? '✓ Hit' : '✕ Miss'} · ${side}` }
}

export function watchAsk(side: '' | 'Yes' | 'No', tracking?: WatchTracking) {
  return side === 'No' ? tracking?.no_ask : tracking?.yes_ask
}
