import { askPrice } from './ui'
import { thresholdHits } from './thresholds'

export function ThresholdTable({ markets, selected, onSelect, games }: {
  markets: { ticker: string; label: string; threshold: number; yes_ask_dollars: string | null }[]
  selected?: string; onSelect: (ticker: string) => void; games?: { value: number | null }[]
}) {
  return <div className="table-scroll threshold-table"><table aria-label={games ? 'Threshold prices and historical hits' : 'Threshold prices'}>
    <thead><tr><th scope="col">Threshold</th><th scope="col">Yes ask</th>{games && <th scope="col">Games hit</th>}</tr></thead>
    <tbody>{[...markets].sort((a, b) => a.threshold - b.threshold).map(market => {
      const count = games && thresholdHits(games, market.threshold)
      return <tr key={market.ticker} className={selected === market.ticker ? 'threshold-selected' : ''}>
        <th scope="row"><button aria-pressed={selected === market.ticker} onClick={() => onSelect(market.ticker)}>{market.label}</button></th>
        <td>{askPrice(market.yes_ask_dollars)}</td>
        {count && <td>{count.total ? `${count.hits} / ${count.total}` : 'Unavailable'}</td>}
      </tr>
    })}</tbody>
  </table></div>
}
