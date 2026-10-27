# College card quote alignment

The Western Kentucky and Missouri State cards previously wrapped their inline
team/spread/price text differently. The college card quote now has a flexible
team column and non-wrapping spread and price columns. Watch and history occupy
a consistent second row. Long names can ellipsize; the full name remains in the
accessible button text, hover title, matchup header and game details.

This is a presentation-only fix on top of `877cb73224c0bd275541bd9d28514f9dd04eaf36`.
Contract selection, pricing, margin calculations, freshness and detail views are unchanged.

## Screenshots

- `college-cards-aligned.jpg`, captured 2026-10-27 21:01:34 UTC: real college
  provider data, rendered in Chrome on the user's Mac. The isolated QA database
  was backed up from `.data/margin-verification/live.sqlite3`; normal public
  refresh-on-open completed before capture. Western Kentucky is now 52¢ and
  Missouri State 51¢. These are captured quotes, not a promise of current prices.
- `desktop-layout-regression.jpg`, captured 2026-10-27 21:02:04 UTC: synthetic
  layout cases, explicitly labeled in the page. No provider calls or personal data.

## Validation

- `npm test`: 37 passed.
- `npm run build`: TypeScript, Vite and desktop branding passed.
- `python scripts/check_bundle.py`: JS 114729/120000 bytes, CSS 7601/12000 bytes.
- Separate strict TypeScript check of the browser regression harness passed
  with Vite client types.
- Actual desktop browser regression: 18 cases passed, using the production
  component/styles at 276, 340 and 382 CSS-pixel card widths. Assertions cover
  row alignment, positive/negative/zero spreads, 1¢/51¢/99.99¢/100¢/unavailable
  prices, long team names, retained full-name access, and no numeric wrapping,
  clipping or horizontal card overflow.
- Visually checked the reported pair and following real cards: quote, controls,
  forecast and strength rows align while preserving the existing dark style.

To rerun the layout checks, start `npm run dev` and open
`/tests/card-spread-layout.html`. The page displays PASS or specific failures.
This browser harness is separate from `npm test`; it needs a real layout engine.
No mobile scope or trading interactions were included.
