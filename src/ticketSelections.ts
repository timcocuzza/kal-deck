export type BetSelection = { description: string; selection: string; market_ticker: string; game_id: string }
export type NotedSelection = { leg: BetSelection; notes?: string }
export type PendingSelection = { id: string; selections: NotedSelection[]; autoStart?: boolean }

export function ticketSelections(selections: NotedSelection[], existing?: { legs: BetSelection[]; notes: string }) {
  const legs = (existing?.legs ?? []).filter(leg => Object.values(leg).some(Boolean)).map(leg => ({ ...leg }))
  const notes = existing?.notes ? [existing.notes] : []
  for (const item of selections) {
    if (item.leg.market_ticker && legs.some(leg => leg.market_ticker === item.leg.market_ticker && leg.game_id === item.leg.game_id)) {
      throw new Error(`${item.leg.description} is already on this ticket. Remove the existing leg before adding it again.`)
    }
    legs.push({ ...item.leg })
    if (item.notes) notes.push(!existing && selections.length === 1 ? item.notes
      : `${item.leg.description}${item.leg.selection ? ` · ${item.leg.selection}` : ''}\n${item.notes}`)
  }
  if (legs.length > 100) throw new Error('A ticket can have at most 100 legs. Select fewer picks.')
  const combinedNotes = notes.join('\n\n')
  if (combinedNotes.length > 10000) throw new Error('Combined notes exceed 10,000 characters. Shorten the notes or select fewer picks; no notes have been removed.')
  return { legs, notes: combinedNotes, kind: legs.length > 1 ? 'combo' as const : 'single' as const }
}
