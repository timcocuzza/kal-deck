# Real application verification — October 27, 2026

This is **real provider data through the normal Deck backend and built React app**, inspected in desktop Chrome. It replaces the earlier synthetic screenshots as evidence of the live data path. No mobile acceptance is claimed, per the requested scope. No models or dependency versions were changed during this follow-up.

## Runtime and provenance

Started on the clean `feat/elo-margins` branch at `eeece65`, matching draft PR #10. Verified `f8a75b589f449d5b1be541b66b9f158f5e50f167` remains an ancestor. No reset, new branch, merge, main push, or deployment.

Traced `src/main.tsx` → report cache → `/api/matchups` / `/api/cfb/matchups` → `SnapshotStore` → the production matchup/identity/venue validators and margin functions. `tests/preview_margins.py` is an explicitly launched test server, never imported by normal runtime. The desktop smoke fixture is confined to the smoke script. No demo fallback exists to remove. Missing inputs produce explicit unavailable forecasts.

Copied only `source_snapshots` from the installed app into `.data/margin-verification/live.sqlite3`, then refreshed through the unmodified `RefreshService` loaders and the app's normal refresh-on-open UI. No personal tracker or watchlist records were copied. Public nflverse, SportsDataverse, ESPN and Kalshi access worked without credentials. The normal app was served with `uvicorn backend.app:app` on `127.0.0.1:8000`; `dist` was the production build. API responses had `Cache-Control: no-store`. Initial sandbox DNS restrictions were resolved with approved network access. An initial verification port of 8765 correctly rejected browser writes; verification moved to the standard allowed origin without changing security settings.

The final HTTP audit was captured around **20:29 UTC**. Exact URLs, successful-download timestamps, published timestamps where supplied, row counts, source context, payload hashes and forecast provenance are in [API evidence](api-evidence.json) and [source evidence](source-evidence.json).

| Input | Final download, UTC | Provider |
| --- | --- | --- |
| NFL schedule / Elo history | 20:27:29 / 20:27:30 | nflverse games.csv |
| NFL team identities / contracts / game identities | 20:27:43 / 20:27:43 / 20:27:45 | Kalshi structured targets, markets, milestones |
| College baseline | 20:24:09 | SportsDataverse |
| College current schedule | 20:24:12 | ESPN scoreboards |
| College strength bundle | 20:24:38 | SportsDataverse archives + ESPN current finals |
| College contracts and identities | 20:24:13 | Kalshi |

The schedule/strength providers did **not** supply separate publication timestamps for these snapshots. Download time proves retrieval, not completeness or the instant a result became public. College historical archives retain their documented seven-day cache; the 24-hour forecast rule covers the current schedule and assembled strength snapshot, whose individual upstream fetch records remain in source context. No claim of independently certified, as-published historical data is made.

## Results

| Actual HTTP report | Available | Unavailable | Available neutral-site games | Verified home / away contracts |
| --- | ---: | ---: | ---: | ---: |
| NFL week 8 | 14 | 0 | 0 | 196 / 160 |
| NFL week 9 | 15 | 0 | 1 | 0 / 0 |
| College week 9 | 56 | 0 | 2 | 913 / 724 |
| College week 10 | 53 | 10 | 1 | 0 / 0 |
| College week 13 | 24 | 45 | 0 | 0 / 0 |

Future weeks without verified open contracts show no comparison; no threshold is invented. Completed NFL week 7 and college week 8 returned no upcoming games, preserving the existing kickoff filter. The API verifier checked 1,993 actual structured contracts, strict `gt` half-point/no-push metadata, participant IDs and signed differences. The input verifier separately replayed saved ratings and recomputed all **162** available margins, including zero venue advantage for:

- Cincinnati at Atlanta, Bernabeu: home margin −3.1742.
- Notre Dame at Navy, Gillette Stadium: −25.3700.
- Florida at Georgia, Mercedes-Benz Stadium: +12.3619.
- Central Michigan at Eastern Michigan, Ford Field: −0.2500.

College week 10 naturally withheld Merrimack at Wake Forest: **“FCS strength is internal only; no public matchup estimate.”** The UI also withheld FCS ratings/statistics. Nine other week-10 games and 45 week-13 games had unverified participants or kickoff context; the latter include four actual TBD opponents. These were not altered fixtures.

In the UI, switching Green Bay over 3.5 to Carolina over 3.5 preserved the Green Bay 5.2 prediction and changed +1.7 to **8.7 points below threshold**. Switching Western Kentucky over 1.5 to Delaware over 1.5 preserved Western Kentucky 2.3 and changed +0.8 to **3.8 points below threshold**. These are differences from Kalshi settlement thresholds, not sportsbook consensus lines or cover probabilities.

## Freshness regression and UI

The bug was in presentation of cached reports: `available` and `status` reflected the original API read indefinitely. The frontend now reassesses source timestamps on every render and cached-view mount, schedules a render at the earliest source's 24-hour boundary plus one millisecond, checks at least every minute for clock changes, and immediately checks on focus, pageshow and visibility changes. Failed report refreshes may retain matchup information, but cannot retain an expired margin or comparison. The backend advertises the existing 24-hour policy; subsequent API reads already reassess it.

Exactly 24 hours remains eligible; anything older is unavailable. Unknown, naive, invalid or future download times fail closed. Prediction as-of and training cutoff are never used to renew source freshness. Server refusals, including FCS/context failures, are never revived. The same real API responses also passed 162 clock-advanced boundary checks. **Those boundary checks simulate elapsed time in the verifier; they are not live 24-hour observations or stale screenshots.** Automated tests cover missing data, stale data, offline report retention, navigation cache reuse, open-view expiry/resume, refresh failure and timer cleanup.

The main display retains the strength-only label, favored team/margin, selected threshold, point difference, and experimental/unavailable status. Early-season estimates keep a short visible status. Other caveats and source timestamps are in native, accessible `details` disclosures on cards and details. There is no “fresh” badge: a download timestamp communicates the evidence more precisely. Inter, dark surfaces and team accents remain; borders are restrained. Desktop cards, long team names, contract selectors, disclosures and detail layouts were visually checked without horizontal overflow. No mobile changes or screenshots were requested in the final scope.

## Screenshots

All seven images below are **real-data desktop captures**, with no injected results, prices or clock changes. Dates are October 27, 2026; times are UTC (the app also shows local EDT). Normal refresh-on-open means early captures can show the previous successful revision while a new provider fetch is in flight; source-detail images show the final timestamps above. [Capture manifest](screenshots.json) includes exact times, image dimensions and hashes.

| Capture | UTC | What it demonstrates |
| --- | --- | --- |
| [NFL cards](nfl-cards.jpg) | 20:26:19 | Real upcoming schedule, home comparison, compact disclosure |
| [NFL away contract](nfl-away-contract.jpg) | 20:27:46 | Carolina over 3.5, 8.7 below threshold |
| [NFL source details](nfl-source-details.jpg) | 20:28:59 | Separate prediction, training and download timestamps |
| [College cards](college-cards.jpg) | 20:23:18 | Experimental status, home and away favorites |
| [College away contract](college-away-contract.jpg) | 20:24:31 | Delaware over 1.5, 3.8 below threshold |
| [College source details](college-source-details.jpg) | 20:24:47 | Actual provider freshness and model caveats |
| [College FCS unavailable](college-fcs-unavailable.jpg) | 20:25:28 | Real unavailable estimate and withheld FCS statistics |

The older images in `../screenshots/` remain **test-only synthetic fixtures**, not live-data evidence.

## Reproduce

Use an isolated database; do not modify the installed app's personal database. Starting empty is supported: open the normal app and let its production loaders download data. To reproduce the exact captured revisions, retain the isolated database and compare the source hashes; later upstream corrections may change results.

```sh
npm run build
DECK_DATABASE_PATH="$PWD/.data/margin-verification/live.sqlite3" \
  .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
# Open the NFL and CFB views, wait for normal refresh completion, then:
node --experimental-strip-types scripts/verify_margin_reports.mjs \
  /tmp/deck-api-evidence.json http://127.0.0.1:8000 2026 \
  nfl:8 nfl:9 nfl:7 cfb:9 cfb:10 cfb:13 cfb:8
PYTHONPATH=. .venv/bin/python scripts/verify_margin_inputs.py \
  .data/margin-verification/live.sqlite3 /tmp/deck-api-evidence.json /tmp/deck-source-evidence.json
```

Both verifiers are read-only against the app/database. They fail if report source revisions no longer match the database; recapture after refreshing. On later dates, started games disappear and counts change. The saved artifact is the record of this run, not a permanent expectation for those URLs.

Checks passed: 243 Python tests, 37 Node tests, TypeScript and production build, `pip check`, bundle budgets, `git diff --check`, npm audit (zero vulnerabilities), pip-audit 2.10.1 (none known), and Gitleaks 8.30.1 (repository history and new evidence, no findings). There is no separate lint command. Dependency manifests/locks were not changed. Final frontend gzip size: 114,608 bytes; CSS: 7,452 bytes, below the 120,000/12,000 budgets.

Remaining limits: Kalshi rate-limited several college **price-history** requests with HTTP 429; those charts reported unavailable history without affecting strength forecasts. Public forecast inputs and structured open contracts refreshed successfully. No timestamp-verified historical sportsbook line dataset was supplied, and no market-aware/cover/EV model was added. The existing 2022–2025 results remain development evidence. The prospective cutoff remains **2026-10-28 00:00 UTC**; these pre-cutoff QA captures are not independent prospective validation, and automated immutable prospective capture remains future work. This PR remains draft pending review of the real-data evidence and final look.
