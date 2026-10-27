# Strength-only matchup margins

NFL and college matchup responses now include `margin_forecast`, displayed on cards and spread details. Existing NFL Elo, college strength configuration, rankings, expected scores, and personal records are preserved. No dependency versions changed.

The canonical prediction is **home final score minus away final score**, including overtime. Contract comparisons use verified `team_id`, positive `threshold`, `operator: "gt"`, and `no_push: true`. Home contracts compare `home_margin - threshold`; away contracts compare `-home_margin - threshold`. Display labels are not parsed. Existing source validation still rejects integer thresholds, mismatched participants/wording/rules, and unverified identities. A strict half-point threshold cannot push on integer football scores. A mean at that threshold is not a settlement forecast.

## Model and availability

NFL uses the approved Elo configuration (K 20, venue Elo 50, retention 2/3), starting in 2002. The separate points conversion fits one coefficient by least squares through the origin:

```
x = home pregame Elo - away pregame Elo + (0 neutral, otherwise 50)
beta = sum(x * final_home_margin) / sum(x * x)
predicted_home_margin = beta * x
```

2002–2006 warm up Elo; results from 2007 onward fit the conversion. At least 256 earlier games and a finite positive coefficient are required. No win-probability transformation, invented constant, ATS Elo update, or hyperparameter search is involved. The terminal 2007–2025 fit is 0.041642688 points/Elo on 5,164 games; **that terminal coefficient is not used to backfill earlier forecasts**. Each historical date has its own past-only fit. Production recomputes from its saved history, so its coefficient can differ.

College uses the existing points benchmark: home strength minus away strength plus two, or zero venue advantage at neutral sites. It remains **experimental**. Its unchanged configuration was previously selected on development data. Joining two ratings is insufficient: season, phase, week, game/team IDs, confirmed participants, exact kickoff, venue flag, scheduled status, and FBS membership must agree between the current schedule and strength bundle. Forecasts involving FCS teams are withheld, preserving the existing restriction on public FCS ratings and derived benchmarks.

Inputs older than 24 hours are unavailable; missing or future/invalid fetch timestamps are unknown. A failed refresh can retain an under-24-hour snapshot with a visible notice. Download age is not proof of statistical completeness. Missing earlier participant results block the forecast. Unknown opponents, TBD/postponed games, completed games, and conflicting contexts have explicit reasons. Early-season and limited-history notices remain visible.

Every response includes game/team IDs, season, venue, kickoff, model version, prediction as-of, rating input cutoff, latest training result kickoff, source fetch/published timestamps, source status/error, availability, and an unavailable reason (null when available). No fallback zero rating or fabricated forecast is displayed. NFL source completion still relies on published nflverse scores, which have no explicit final-status field.

## Chronology, corrections, and prospective evaluation

Forecasts freeze at the beginning of the UTC date with an additional **24-hour result embargo**: only games kicked off before the preceding UTC midnight can contribute. This conservative lag avoids treating late-night partial scores as known at midnight when the archives lack final timestamps. It deliberately makes the forecast's rating inputs older than the adjacent latest-strength display. Future scheduled games use this frozen strength without simulating intervening games.

Historical replay records ratings before each result. Same-date games are predicted together. The NFL fit and both rolling home-only baselines learn only after the embargo. The audit verifies that neither participant has an earlier game inside that embargo before using its pregame rating. Historical college replay still includes FCS results internally and uses past-only division centers and season regression. Evaluation rows expose their origin and training cutoff.

Replaying after a historical score correction rebuilds all affected later estimates. It does not accumulate duplicate updates or insert a game's own result into its pregame rating. These are **reconstructed forecasts using corrected archives**, not proof of what a provider published at each historical instant. Historical membership/completeness is not independently certified. Neither the embargo nor a recent fetch establishes as-published data availability.

**Prospective cutoff: 2026-10-28 00:00 UTC.** Freeze these model versions and this protocol before that cutoff. Do not retune using prospective outcomes. To evaluate prospectively, archive each actual API forecast and the exact input snapshot hashes before kickoff; keep corrections as separate revisions, not replacements of issued predictions. Score all eligible FBS-v-FBS and NFL forecasts, disclose unavailable/late forecasts, and report MAE/RMSE/bias by sport, season, venue, and early-season status. No prospective archive or prospective result is claimed by this PR; automated immutable capture is future work. Any changed model requires a new version and evaluation window.

## Reproduce the development audit

The already-inspected **2022–2025 seasons are development evidence**, not an untouched holdout. No margin coefficient or college setting was selected using these reported evaluation metrics. Expanding fits may learn from earlier evaluation dates, never the current date or a future result.

Download the public archives into a separate directory (no production database writes):

```sh
mkdir -p /tmp/deck-margin-data
curl -L --fail --silent --show-error https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv -o /tmp/deck-margin-data/nfl-games.csv
for year in $(seq 2014 2025); do
  curl -L --fail --silent --show-error "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/cfb_schedules/cfb_schedules_${year}.csv.gz" -o "/tmp/deck-margin-data/cfb_schedules_${year}.csv.gz"
done
PYTHONPATH=. .venv/bin/python scripts/backtest_margins.py /tmp/deck-margin-data docs/research/margins
```

[Machine-readable results](research/margins/results.json) include input SHA-256 hashes, all seasonal metrics, terminal fit metadata, market coverage, and blockers. [Per-game predictions](research/margins/predictions.csv.gz) are deterministic gzip CSV. Upstream corrections can change hashes and results; preserve the original downloaded files to reproduce the exact source revision.

| Development 2022–2025 | Games | MAE | RMSE | Bias (prediction − actual) |
| --- | ---: | ---: | ---: | ---: |
| NFL strength | 1,139 | 9.970 | 12.899 | −0.176 |
| NFL rolling home-only | 1,139 | 10.712 | 13.871 | −0.151 |
| NFL zero margin | 1,139 | 10.865 | 14.063 | −2.329 |
| College strength, FBS-v-FBS | 3,174 | 13.174 | 16.631 | −1.628 |
| College rolling home-only | 3,174 | 15.657 | 20.083 | −0.558 |
| College zero margin | 3,174 | 16.076 | 20.577 | −4.362 |

Home-only estimates the earlier non-neutral home margin mean and predicts zero at neutral sites. College 2014–2016 warms up the model; evaluation is FBS-v-FBS, while internal updates include Division I opponents. The negative college bias is a reason to retain the experimental label, not a correction fitted on this evaluation set.

## Separate historical market path

`--lines /path/to/lines.csv` enables an **offline-only** comparison. No market model is imported into production. Required CSV columns:

```
sport,game_id,season,home_id,away_id,kickoff,quoted_at,observed_at,source,line_convention,home_line
```

`home_line` must be the market's expected home margin: home −7.5 sportsbook notation becomes **+7.5**, away −7.5 becomes **−7.5**. `line_convention` must explicitly equal `home_expected_margin`; raw sportsbook signs are rejected. The caller must document and verify the provider's original semantics before conversion. Use a consistent provider/book or explicitly constructed consensus series; this tool does not manufacture consensus from different books. It uses the most recent eligible supplied quote per game, so the input's provider policy matters.

Both quoted and observed timestamps must exist, be timezone-aware, satisfy quoted ≤ observed ≤ forecast origin, and precede kickoff. Exact sport/game ID, season, teams, and kickoff must join. Nonfinite/implausible values, duplicate same-source timestamps, unknown signs, and future/unknown times are rejected with counts. Results report joined/input/eligible/paired game counts; inspect coverage before interpreting metrics. A recently downloaded historical closing-line file does not demonstrate earlier availability. Do not fill missing games or replace early lines with closing lines.

On paired timestamp-verified games, the script compares market-only, strength-only, a blend, and an optional constant ATS-residual correction. Training is restricted to 2017–2021, with at least 256 paired games. The strength blend weight is chosen from 0, .25, .5, .75, 1 by training MAE; zero wins ties. A median training residual is compared with zero correction; zero wins ties. The 2022–2025 comparison is development evidence only, not independent validation of that selection. Retraining or a more elaborate residual model needs its own predeclared chronological protocol. Zero strength weight/correction is explicitly allowed.

**Current blocker:** no timestamp-verified historical line input was supplied. The available NFL schedule's line columns do not provide the quote/observation history needed at the daily forecast origin, and this run has no verified college historical-line archive. Therefore market-only/blended/residual metrics are unavailable, not invented. No paid access or credentials were requested.

The UI difference is a point difference from a Kalshi contract threshold, not a sportsbook consensus line, cover probability, proven betting edge, or expected profit. Cover/EV work additionally requires a validated conditional margin distribution, exact settlement rules, executable Yes/No prices, fees and costs. None is inferred from this mean.

## Verification and screenshots

Run `npm test`, `npm run build`, `.venv/bin/python -m unittest discover -s tests -v`, `.venv/bin/python scripts/check_bundle.py`, and `.venv/bin/python -m pip check`. The repository has no separate lint command; `git diff --check` checks patch whitespace. Tests cover home/away signs, neutral venues, strict thresholds, changed contracts, missing/stale/failing sources, unknown context, FCS restrictions, early season, prior pending results, historical corrections, daily fit freezes and timestamp/sign/join rejection.

For a safe UI acceptance fixture, run `PYTHONPATH=.:tests .venv/bin/python tests/preview_margins.py` after building, then open `http://127.0.0.1:8765`. It uses synthetic results and quotes with the real forecast functions and built app. It never opens personal storage, refreshes sources, or submits bets. Screenshots under [research/margins/screenshots](research/margins/screenshots) show fixture data, not live predictions or executable quotes.

Verified locally on October 27: 242 Python tests, 33 Node tests, TypeScript/build, pip consistency, patch whitespace, and bundle budgets passed. The optional date-frozen NFL replay was identical to the approved replay on all 6,499 input games. No separate lint configuration exists.

Native Chrome acceptance verified NFL and college cards/details, a college threshold change (7.5 → 14.5 changes +4.9 → −2.1), and away-team changes (college −15.9, NFL −16.3). The favored-team prediction stayed unchanged as contracts changed. College stale inputs remain unavailable while the matchup stays visible. Screenshots: [NFL cards](research/margins/screenshots/nfl-cards.png), [NFL away contract](research/margins/screenshots/nfl-away-contract.png), [college cards / stale inputs](research/margins/screenshots/college-cards.png), [college away contract](research/margins/screenshots/college-away-contract.png). This was a desktop fixture acceptance pass; live source freshness and real contract availability were not exercised.
