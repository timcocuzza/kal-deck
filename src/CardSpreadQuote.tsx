import { askPrice } from './ui'

// Keep the numeric columns intact when a college team name needs more room.
export function CardSpreadQuote({ team, spread, yesAsk }: {
  team: string; spread: number; yesAsk: string | null
}) {
  const line = `${spread < 0 ? '−' : spread > 0 ? '+' : ''}${Math.abs(spread)}`
  return <span className="card-spread-quote">
    <span className="card-spread-team" title={team}>{team}</span>
    <span className="card-spread-line">{line}</span>
    <strong className="card-spread-price">{askPrice(yesAsk)}</strong>
    <small>Yes ask · before fees</small>
  </span>
}
