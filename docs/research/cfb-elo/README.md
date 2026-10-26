# College strength rating experiment

October 24, 2026 · `feat/college-football` · offline research only.

## Recommendation

Use a bounded scoring-margin performance rating as the implementation candidate. It permits an unimpressive win to reduce a team's rating and a competitive loss to increase it, as requested. Include individually rated FCS opponents internally, retain separate facet rankings, and show schedule strength beside the overall rating. This is an Elo-style update process in **points of strength**, not conventional win/loss Elo or a calibrated win/cover probability.

The training-selected candidate updates each participant by **20% of the scoring-margin error, limited to ±28 points of error**. Home field contributes two points to the benchmark, with zero at neutral sites. Each team can therefore gain or lose at most 5.6 strength points per game. It retains **40% of the prior season's deviation from its division baseline**. That is the strongest carryover permitted in the predeclared light-carryover search, not a claim that 40% is globally optimal or a production setting already approved by the user.

Twenty-five percent carryover remains a reasonable product preference, but it performed worse in this experiment. A separate 67% diagnostic did better than 40%; do not silently substitute it for the user's preference. No live rating, source refresh, database schema, or NFL behavior changed.

## Data and chronology

Audited all 25 available completed-season bulk files, 2001–2025, from [SportsDataverse's schedule release](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/cfb_schedules). Files include season-specific FBS/FCS classifications, final scores, kickoff dates and venue flags. Exact URLs, hashes, counts and notices are in [source-audit.json](source-audit.json).

- The 2001–2002 files contain no FCS-only games. The 2004 and 2008 files fail the distinct-team/game-date check because games appear under different IDs. These files were rejected, not silently deduplicated.
- Older FCS coverage is also incomplete. ESPN's Montana 2012 team schedule has 11 Division I results versus two in the bulk file. All nine missing identities are recorded in [coverage-checks.json](coverage-checks.json).
- The experiment therefore replays **17,706 completed Division I games from 2014–2025**. One 2024 canceled game is excluded despite its zero score placeholders. Games against opponents below Division I are excluded consistently.
- Six later team-season spot checks reconcile all expected Division I game IDs; one venue flag disagrees. Low game counts for transitioning programs in these checks are explained by games outside Division I, rather than missing Division I results. These spot checks are not exhaustive coverage certification.
- North Dakota State at South Dakota State on October 3, 2015 is wrongly marked neutral in the bulk file. ESPN and [South Dakota State's official opponent history](https://gojacks.com/sports/football/opponent-history/north-dakota-state/130) identify a home game in Brookings. [venue-corrections.json](venue-corrections.json) guards the correction with exact identities, date and scores. With frozen settings, its effect on held-out MAE is less than 0.000001 points for every tested baseline.
- Most FCS-only historical rows have `completed=true` and valid scores but no status name. They are accepted under that explicit historical convention. A future current-season loader must verify final status separately.
- Spring 2021 games assigned to the 2020 season stay there. Actual dates order the replay, and offseason regression happens once per source season. The 2020 game graph has an isolated two-team component; inherited historical ratings still connect those programs to earlier seasons.
- Predictions for all games on one UTC date are frozen before applying that date's results. Reversing within-date game order produces identical predictions. No final completion timestamps are inferred from kickoff times.

## Experiment and results

[protocol.json](protocol.json) was written before parameter comparisons. The split is 2014–2016 warmup, 2017–2021 parameter selection, and 2022–2025 held-out evaluation. The current 2026 season is excluded. Candidate selection receives no held-out games; [selection-lock.json](selection-lock.json) records the chosen settings, training hash and code hash before held-out scoring. Earlier held-out results update ratings chronologically, with frozen parameters.

Compared 288 capped/smooth performance configurations, 48 unbounded performance configurations, 27 win-only Elo configurations, the existing NFL parameter baseline, and a division/venue-only baseline. The primary selection metric is pregame margin mean absolute error (MAE) on FBS-versus-FBS games. This is an internal quality check for team strength, not a user-facing spread recommendation. Elo baselines use a training-only conversion from rating differences to points for a common comparison. The NFL baseline adapts college team lifecycle/division centers; it does not run the NFL application on college data unchanged.

Held-out results cover **3,174 FBS-versus-FBS games**:

| Approach | Margin MAE, lower is better | RMSE | Winner direction accuracy |
| --- | ---: | ---: | ---: |
| Selected bounded performance rating | 13.174 | 16.631 | 70.01% |
| Unbounded performance baseline | 13.173 | 16.641 | 69.97% |
| NFL-style margin Elo baseline | 13.325 | 16.821 | 69.47% |
| Tuned win-only Elo | 13.835 | 17.508 | 67.83% |
| Division and venue only | 15.653 | 20.094 | 58.30% |

The bounded rating beats win-only Elo here. Its advantage over NFL-style margin Elo is small and inconclusive: the descriptive 95% season/week-block interval for the MAE difference is **−0.362 to +0.053 points**. Its accuracy is effectively tied with the unbounded baseline. Bounded updates are recommended because they satisfy the user's limit on blowout influence, not because this experiment proves an accuracy improvement over unbounded updates. Four held-out seasons and block resampling cannot establish universal superiority or betting profitability.

Carryover sensitivities, with each permitted candidate selected on training only:

| Retained deviation | Selection MAE | Held-out MAE |
| --- | ---: | ---: |
| 0% | 14.232 | 13.787 |
| 15% | 13.913 | 13.531 |
| 25% | 13.726 | 13.377 |
| 40% | 13.483 | 13.174 |
| 67%, separate fixed-setting diagnostic | Not eligible for selection | 12.915 |

At 40%, first-three-game FBS matchup MAE is 15.189; at 25%, it is 15.936. Higher carryover helps early-season results in this sample. Keep the stronger-carryover result visible as a tradeoff; changing the preference or tuning further against these held-out years would require explicitly treating them as development data.

Including FCS results improves overall held-out FBS–FBS MAE by about 0.084 points, but the block interval crosses zero. It also makes FCS games meaningful to a team's rating, which is a product requirement. On 485 FBS–FCS held-out games, MAE is 13.764. Those mismatches are easier to classify by winner and must not inflate the headline FBS–FBS evaluation.

The selected candidate underestimates home margin by 1.628 points on average in held-out FBS–FBS games and by 3.924 in FBS–FCS games. That residual bias is another reason not to present its benchmark as a calibrated market spread. No parameter was retuned to remove it after viewing the holdout.

Winners lose rating in 674 of the 3,174 held-out FBS–FBS games (about 21%). [comparison.json](comparison.json) contains actual examples, season breakdowns and the complete metrics. [robustness.json](robustness.json) contains frozen-setting venue/carryover/FCS diagnostics; its early-season comparisons use identical game IDs. [held-out-predictions.csv.gz](held-out-predictions.csv.gz) contains the paired FBS–FBS predictions for independent recomputation.

## Remaining gates and scope

Historical NCAA membership and complete all-team schedules are not independently certified. The initial files prove that passing schema checks is insufficient. Final-score margins include overtime; complete regulation scoring is not established. Historical snapshots include later corrections and are not archives of exactly what was published before each game. Results-based ratings cannot account directly for roster changes, injuries or coaching changes. Returning programs and division transitions need explicit coverage notices; a move to FBS must never grant an immediate rating bonus.

Production work should add a college history source with atomic validation/retention, a current FCS final-results feed, broader venue/membership checks, source freshness and missing-history reporting. The current college schedule source fetches FBS-participant games only and is therefore insufficient by itself for internal FCS ratings. Overall ratings, SoS, logs and UI remain future integration work. No props, recruiting inputs, paid services, betting lines, or cover probabilities enter this experiment.

## Reproduction

Download the `.csv.gz` files named in `source-audit.json` to a scratch directory, preserving their recorded hashes. For coverage checks, use the exact URLs in `coverage-checks.json` and cache them as `elo-team-{team_id}-{season}-{seasontype}.json`; Montana 2012 uses `elo-montana-2012.json`.

```sh
python3 scripts/compare_college_elo.py /tmp/deck-cfb-audit docs/research/cfb-elo
python3 scripts/audit_college_elo_coverage.py /tmp/deck-cfb-audit docs/research/cfb-elo/coverage-checks.json
python3 scripts/check_college_elo_robustness.py /tmp/deck-cfb-audit docs/research/cfb-elo
.venv/bin/python -m unittest discover -s tests -p 'test_college_elo_research.py'
```

The research scripts use the standard library. They read cached public files and write evidence artifacts only. They do not import the application, download data, or touch personal SQLite storage. Repeat parameter searches only against the declared training split. Source downloads can change; hashes are required for exact numerical reproduction.

Validation passed: all 204 backend tests, including ten research tests for update direction, bounded influence, date batching, no future-result leakage, spring-season regression, division changes, duplicate identities, canceled games, corrections, neutral sites and held-out selection rejection. Independent recomputation from the saved CSV matches all five headline MAEs; protocol, experiment-code and selection-lock hashes match their artifacts. `git diff --check` passes. Frontend/build checks were not repeated because this stage changes no application runtime code.
