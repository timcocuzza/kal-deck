# College strength rating

October 26, 2026. Implemented on `feat/college-football`; development preview only.

## Purpose and accepted decisions

Give the user an explainable overall view of team strength and schedule difficulty alongside the existing six facet rankings. The user approved ratings that can fall after a win or rise after a loss, individually rated FCS opponents used internally without displaying FCS statistics/ratings, and light prior-season carryover. The October 26 instruction to proceed adds an explicit goal: support the user's own AP-style top 25 with defensible reasoning, as well as spread research. Strength order is one input to that judgment; the user's ballot may weigh records and head-to-head results differently. No predicted spreads or cover probabilities are required.

## Development configuration

Maintain FBS and FCS teams on one internal scale measured in points of strength. For a home team:

```text
benchmark = home_rating - away_rating + venue_adjustment
error = actual_home_scoring_margin - benchmark
change = 0.20 × clamp(error, -28, +28)
home_rating += change
away_rating -= change
```

The venue adjustment is two points at home and zero at neutral sites. For example, a team with a pregame benchmark of +20 that wins by three loses 3.4 strength points; its opponent gains 3.4. A 60-point overperformance changes each team by 5.6, the same maximum as a 28-point overperformance. The cap applies to **performance relative to the benchmark**, not directly to the final winning margin. Overtime currently uses the published final margin and must be disclosed.

The training-selected candidate retains 40% of each program's previous deviation from its division baseline. Twenty-five percent remains a viable lighter option, with a measured accuracy tradeoff. The 67% diagnostic performed better but is outside the agreed light-carryover search. The development implementation uses this 40% candidate under the user’s instruction to proceed; it remains a research configuration, not a proven optimal setting.

Division baselines are means learned from the previous season's active teams, frozen before the next season begins. The initial historical warmup starts both divisions at zero; cross-division games establish their separation. Existing teams regress toward their **previously observed** division baseline on a transition, so reclassification does not inject a free rating increase. New teams receive a division prior and an insufficient-history notice. For returning teams, retain `retention ^ elapsed_seasons` of their deviation from the latest available division baseline. Freeze predictions within each UTC date, then apply results together. Recompute from validated saved history after corrections rather than incrementing a stored rating blindly.

This is a performance rating with Elo-style sequential updates. Do not reuse the NFL 400-point probability conversion or imply that college and NFL rating values are comparable. Prefer a **College strength** label with rating, FBS rank and last-game change; any alternate presentation scale must be a fixed, documented transform of the internal rating.

## Strength of schedule and interface

- Show overall strength, FBS rank, season change, latest rated result and counted-game coverage in the same compact card/history pattern used by NFL Elo.
- Show **schedule faced** beside it: the mean of each opponent's pregame overall rating, per meeting, including internal FCS ratings. Both displayed schedule measures account for venue: opponent rating minus two when the team played at home, plus two when away, and unchanged at neutral sites. FBS schedule ranks compare the same measure and completed-game scope.
- Offer a separately labeled **opponents now** view using their latest ratings to reassess the schedule. Historical pregame context never changes merely because an opponent improves later. Neither measure is an additional rating bonus; opponent strength is already in the update.
- Keep overall opponent strength distinct from the existing passing/rushing/protection/pass-rush opponent context. Do not silently alter those descriptive facet rankings.
- FBS game logs show date, opponent name, result, venue, before/after rating and change. FBS opponents may show their pregame rank/rating. For FCS opponents, show the name, result and resulting FBS-team rating change, but suppress their individual rating/rank and detailed benchmark that would trivially expose that rating. Aggregate SoS may include internal FCS strength, with the scope stated.
- Show early-season/incomplete-history notices based on coverage; do not invent numerical confidence intervals. Unknown membership, missing finals and identity conflicts must remain visible rather than silently excluding an inconvenient result. FCS-only schedules and ratings do not become user-facing tabs.

## Evidence and limitations

The [offline experiment](research/cfb-elo/README.md) audited 2001–2025 files and replayed 17,706 games from the usable 2014–2025 window. On 3,174 held-out FBS–FBS games, selected margin MAE was 13.174 points, versus 13.325 for the NFL-style margin baseline and 13.835 for tuned win-only Elo. The small NFL-baseline advantage is inconclusive; the unbounded performance baseline is effectively tied. Bounded updates are valuable primarily because they meet the requested behavior and limit outlier influence.

Do not claim comprehensive historical coverage or calibrated forecasts. Older FCS histories contain omissions and duplicates; the implementation begins in 2014. The audited 2015 venue error has an identity-guarded correction. Current FBS and FCS results now refresh through ESPN, while overtime detail remains incomplete. Source-specific season membership still needs independent validation. The experiment keeps all known limitations and corrections in reproducible artifacts.

## Implemented integration

- `cfb_strength:{season}` stores validated Division I schedules from 2014 through the selected season. Historical archives have a seven-day cache. Current results combine ESPN FBS and FCS scoreboards, reconcile every known Division I baseline game, and reject missing IDs, lost finals, unclassified real participants, ambiguous venue flags, or conflicting scores between pages. Known unplayed TBD/TBA placeholders never become rated teams. Postseason feeds are added from December; live postseason behavior still needs end-of-season verification.
- Neutral-site nominal home/away reversals are accepted only when both sources explicitly say neutral, and teams, kickoff, completion and per-team final scores agree exactly. Other participant conflicts fail closed. Correction IDs and source provenance remain in snapshot metadata.
- `backend/college_rating.py` replays the research candidate without importing the experiment at runtime. `backend/college_strength.py` provides FBS-only evidence via `/api/cfb/strength`. Failures preserve the last successful snapshot. Started games without a confirmed final are flagged rather than counted.
- `#cfb/ratings` provides searchable FBS strength/schedule ordering, a first-25 or all-team view, overall/FBS records, and records against the current Deck strength top 25. Team dialogs show three wins over the strongest current FBS opponents, losses to review (including FCS losses), and all rated season results with venue, opponent pregame/current ranks, and rating movement. These ranks are not AP ranks. A saved, manually ordered ballot and written rationales are a future layer.
- Game cards and matchup details share the same FBS rating/record/schedule summaries and evidence dialogs. Existing facet rankings retain their definitions.
- Tests cover replay parity, chronology, spring seasons and transitions, offseason priors, pending/canceled/postponed games, source caching/failure retention, venue correction guards, neutral-label reconciliation, and FCS suppression. Current live validation is recorded in [cfb-strength-validation.json](cfb-strength-validation.json).

No recruiting, roster, injury, conference prestige, betting-line inputs, player props or separate offense/defense model are included. Those would need their own data justification and validation.
