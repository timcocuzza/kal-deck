import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { historySnapshot, subscribeHistory, ensureSpreadHistory, loadSpreadHistory, historyWindow, historyPath, historyX, historyY } from './spreadHistory'

function date(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString(undefined, { timeZoneName: 'short' })
}
function percent(value: number | string | null) {
  return value === null ? 'Unavailable' : `${(Number(value) * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`
}
function axisDate(timestamp: number, hours: number) {
  return new Date(timestamp * 1000).toLocaleString(undefined, hours <= 24
    ? { hour: 'numeric', minute: '2-digit' } : { month: 'short', day: 'numeric' })
}

export function WeekHistoryButton({ tickers }: { tickers: string[] }) {
  const entries = useSyncExternalStore(subscribeHistory, historySnapshot)
  const pending = tickers.filter(ticker => entries[ticker]?.status).length
  return <button disabled={!tickers.length || pending > 0} onClick={() => void loadSpreadHistory(tickers)}>
    {pending ? 'Loading lines…' : 'Refresh lines'}
  </button>
}

export function SpreadHistory({ ticker, label, compact = false }: { ticker: string; label: string; compact?: boolean }) {
  const entries = useSyncExternalStore(subscribeHistory, historySnapshot)
  const entry = entries[ticker]
  useEffect(() => { void ensureSpreadHistory([ticker]) }, [ticker])
  const data = entry?.data
  const [hours, setHours] = useState(168)
  const [inspected, setInspected] = useState<number | null>(null)
  const id = useId()
  const chartRef = useRef<SVGSVGElement>(null)
  const [chartWidth, setChartWidth] = useState(480)
  useLayoutEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const resize = () => setChartWidth(Math.max(200, Math.round(chart.getBoundingClientRect().width)))
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(chart)
    return () => observer.disconnect()
  }, [!!data, compact])
  const points = data ? historyWindow(data, hours) : []
  const start = data ? Math.max(data.context.start_ts, data.context.end_ts - hours * 3600) : 0
  const end = data?.context.end_ts ?? 1
  const valid = points.filter(point => point.midpoint !== null)
  const index = inspected === null ? points.length - 1 : Math.min(inspected, points.length - 1)
  const point = points[index]
  if (compact) return <div className="sparkline" role="img"
    title={entry?.error ? `History refresh failed: ${entry.error}. ${data ? 'Saved history retained.' : 'No history available.'} Use Refresh lines to retry.` : data ? `7-day YES midpoint · Fetched ${new Date(data.fetched_at).toLocaleString()}` : 'Loading history'}
    aria-label={`${label}: 7-day YES midpoint history. ${entry?.status ? 'Loading.' : entry?.error ? 'Refresh failed.' : valid.length ? 'Gaps indicate missing quotes.' : 'No history available.'}`}>
    {!!valid.length && <svg viewBox="40 10 430 152" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id={`${id}-line`}><stop stopColor="var(--away-color, #b8c6df)" /><stop offset="1" stopColor="var(--home-color, #b8c6df)" /></linearGradient></defs>
      <path d={historyPath(points, start, end)} stroke={`url(#${id}-line)`} vectorEffect="non-scaling-stroke" />
      {points.filter((item, index) => item.midpoint !== null && points[index - 1]?.midpoint == null && points[index + 1]?.midpoint == null)
        .map(item => <circle key={item.timestamp} cx={historyX(item.timestamp, start, end)} cy={historyY(item.midpoint!)} r="2" fill={`url(#${id}-line)`} />)}
    </svg>}
  </div>
  return <section className={`spread-history${compact ? ' compact' : ''}`} aria-label={`${label} price history`}>
    <div className="controls">
      <strong>YES midpoint history</strong>
      <button disabled={!!entry?.status} onClick={() => void loadSpreadHistory([ticker])}>
        {entry?.status === 'queued' ? 'Queued…' : entry?.status === 'loading' ? 'Loading…' : data ? 'Refresh history' : 'Load history'}
      </button>
    </div>
    {!data && !entry?.status && !entry?.error && <p className="source-note">Load the past seven days from Kalshi.</p>}
    {entry?.error && <p role="alert" className="source-note">History refresh failed: {entry.error}
      {data ? ' Showing the previous download.' : ' No history is available.'}
      {entry.attemptedAt && ` Attempted ${new Date(entry.attemptedAt).toLocaleString()}.`}</p>}
    {data && <>
      <div className="controls history-ranges" aria-label="History range">
        {[[168, '7 days'], [24, '24 hours'], [6, '6 hours']].map(([value, title]) => <button key={value}
          aria-pressed={hours === value} onClick={() => { setHours(Number(value)); setInspected(null) }}>{title}</button>)}
      </div>
      <svg ref={chartRef} viewBox={`0 0 ${chartWidth} 192`} role="img" aria-labelledby={`${id}-title ${id}-description`}
        onPointerMove={event => {
          const box = event.currentTarget.getBoundingClientRect()
          const timestamp = start + (((event.clientX - box.left) / box.width * chartWidth - 44) / (chartWidth - 60)) * (end - start)
          setInspected(Math.max(0, Math.min(points.length - 1, Math.round((timestamp - (points[0]?.timestamp ?? start)) / 3600))))
        }}>
        <title id={`${id}-title`}>{label}: historical YES bid/ask midpoint</title>
        <desc id={`${id}-description`}>Hourly closing quotes on a fixed 0 to 100 percent scale. Missing hours break the line. {valid.length} of {points.length} hourly points available. Use the slider below to inspect each hour.</desc>
        {[0, 0.5, 1].map(value => <g key={value}>
          <line x1="44" x2={chartWidth - 16} y1={historyY(value)} y2={historyY(value)} className="history-grid" />
          <text x="37" y={historyY(value) + 4} textAnchor="end">{value * 100}%</text>
        </g>)}
        <path d={historyPath(points, start, end, chartWidth)} className="history-line" />
        {valid.map(item => <circle key={item.timestamp} cx={historyX(item.timestamp, start, end, chartWidth)} cy={historyY(item.midpoint!)} r="1.7" className="history-point" />)}
        {point && <line x1={historyX(point.timestamp, start, end, chartWidth)} x2={historyX(point.timestamp, start, end, chartWidth)} y1="16" y2="156" className="history-cursor" />}
        <text x="44" y="181">{axisDate(start, hours)}</text>
        <text x={chartWidth - 16} y="181" textAnchor="end">{axisDate(end, hours)}</text>
      </svg>
      {!valid.length && <p role="status">No valid two-sided hourly quotes in this range.</p>}
      {point && <>
        <input className="history-slider" type="range" min="0" max={points.length - 1} step="1" value={index}
          aria-label={`Inspect hourly history for ${label}`} aria-describedby={`${id}-point`}
          aria-valuetext={`${date(point.timestamp)}: ${percent(point.midpoint)}`}
          onChange={event => setInspected(Number(event.target.value))} />
        <p id={`${id}-point`} className="source-note history-inspection">{date(point.timestamp)}<br />
          {point.midpoint === null ? 'No valid two-sided quote supplied for this hour.'
            : `Midpoint ${percent(point.midpoint)} · Bid ${percent(point.bid)} / Ask ${percent(point.ask)}`}</p>
      </>}
      <p className="source-note">{valid.length}/{points.length} hourly points available. Gaps are not filled. Indicative quotes, not traded prices.</p>
      <p className="source-note">Fetched {new Date(data.fetched_at).toLocaleString()}. Window ends {date(end)}.</p>
      {!compact && <details><summary>Hourly quotes and source</summary>
        <p className="source-note"><a href={data.url} target="_blank" rel="noreferrer">Kalshi history</a> · {ticker}<br />{date(start)} – {date(end)}</p>
        <div className="table-scroll"><table><caption>{label} hourly closing quotes</caption>
          <thead><tr><th>Hour ending</th><th>YES bid</th><th>YES ask</th><th>Midpoint</th></tr></thead>
          <tbody>{points.map(item => <tr key={item.timestamp}><td>{date(item.timestamp)}</td>
            <td>{percent(item.bid)}</td><td>{percent(item.ask)}</td><td>{percent(item.midpoint)}</td></tr>)}</tbody>
        </table></div>
      </details>}
    </>}
  </section>
}
