// Open /tests/card-spread-layout.html under npm run dev. Real component/styles,
// synthetic edge cases only; no app storage, provider requests or trading actions.
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { CardSpreadQuote } from '../src/CardSpreadQuote'
import '../src/styles.css'

const cases = [
  { team: 'Western Kentucky', spread: -1.5, yesAsk: '.51', line: '−1.5', price: '51¢' },
  { team: 'Missouri State', spread: -5.5, yesAsk: '.51', line: '−5.5', price: '51¢' },
  { team: 'North Carolina State Wolfpack', spread: 49.5, yesAsk: '.9999', line: '+49.5', price: '99.99¢' },
  { team: 'Louisiana-Monroe', spread: -49.5, yesAsk: '.01', line: '−49.5', price: '1¢' },
  { team: 'University of Massachusetts Amherst', spread: 0, yesAsk: '1', line: '0', price: '100¢' },
  { team: 'Miami', spread: 3.5, yesAsk: null, line: '+3.5', price: 'Unavailable' },
]
const widths = [276, 340, 382] // Cards in the existing three/four-column desktop grids.

function LayoutRegression() {
  const [result, setResult] = useState('Checking desktop layout…')
  useEffect(() => {
    let disposed = false
    void document.fonts.ready.then(() => requestAnimationFrame(() => {
      const failures: string[] = []
      const check = (ok: boolean, message: string) => { if (!ok) failures.push(message) }
      for (const group of document.querySelectorAll<HTMLElement>('[data-width]')) {
        const cards = [...group.querySelectorAll<HTMLElement>('.game-card')]
        const offsets: number[][] = []
        cards.forEach((card, index) => {
          const test = cases[index], prefix = `${group.dataset.width}px ${test.team}`
          const team = card.querySelector<HTMLElement>('.card-spread-team')!
          const line = card.querySelector<HTMLElement>('.card-spread-line')!
          const price = card.querySelector<HTMLElement>('.card-spread-price')!
          check(team.textContent === test.team && team.title === test.team, `${prefix}: full name lost`)
          check(line.textContent === test.line && price.textContent === test.price, `${prefix}: sign/price changed`)
          for (const item of [line, price]) {
            check(item.scrollWidth <= item.clientWidth + 1, `${prefix}: clipped numeric value`)
            const range = document.createRange(); range.selectNodeContents(item)
            check(range.getClientRects().length === 1, `${prefix}: wrapped numeric value`)
          }
          check(card.scrollWidth <= card.clientWidth, `${prefix}: card overflow`)
          const selectors = ['.college-card-market', '.card-spread-line', '.card-spread-price', '.card-market-tools', '.margin-forecast']
          offsets.push(selectors.map(selector => card.querySelector(selector)!.getBoundingClientRect().top - card.getBoundingClientRect().top))
        })
        offsets.forEach(row => row.forEach((offset, i) => check(Math.abs(offset - offsets[0][i]) < 1,
          `${group.dataset.width}px: neighboring row ${i} misaligned`)))
      }
      if (!disposed) setResult(failures.length ? `FAIL: ${failures.join('; ')}` : 'PASS — 18 desktop cases: aligned quote/controls/forecast rows; full names accessible; all signs and prices intact; no numeric wrapping or overflow.')
    }))
    return () => { disposed = true }
  }, [])
  return <main style={{ padding: 24 }}>
    <h1>College card layout regression</h1>
    <p>Synthetic layout cases — not real quotes. Uses the production quote component and styles.</p>
    <p role="status" style={{ color: '#b2cdb1' }}>{result}</p>
    {widths.map(width => <section key={width} data-width={width} className="college-view" style={{ margin: '24px 0' }}>
      <h2>{width}px desktop cards</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, marginTop: 12 }}>
        {cases.map(test => <article className="game-card" key={test.team} style={{ width }}>
          <div className="game-market college-card-market">
            <button className="game-spread"><CardSpreadQuote {...test} /></button>
            <div className="card-market-tools"><button className="watch-button">☆ Watch</button><div className="sparkline" aria-label="Synthetic history placeholder" /></div>
          </div>
          <section className="margin-forecast compact"><strong>Forecast alignment reference</strong></section>
        </article>)}
      </div>
    </section>)}
  </main>
}
createRoot(document.getElementById('root')!).render(<LayoutRegression />)
