# College football feasibility audit

Audit captured October 24, 2026. This is research and a saved matchup preview; the running application has not changed.

## Conclusion

A college football research tab has a credible path without recurring data fees. Anonymous public feeds supplied schedules, six candidate facet rankings, game logs, and a verified sample spread with price history. The remaining technical gates are **statistics freshness, precise EPA definitions, and independent all-FBS coverage**. The current evidence does not establish a production-ready feed.

The intended product follows the NFL app: information for the user's judgment, spreads first, familiar paired rankings and logs, and more prominent opponent-strength context. Player props are omitted. A complex Elo system is not a prerequisite; it would require a separate justification and method review.

## Sources and coverage

| Feature | Evidence | Limitation |
| --- | --- | --- |
| Schedules, kickoff, status | Anonymous ESPN week-8 feed matched all 56 games and home/away IDs in the saved schedule | Full-season coverage is not independently verified; request limits behaved inconsistently |
| Passing/rushing offense and defense | SportsDataverse advanced tables supply game-level EPA and supporting measures | EPA per play is rounded to two decimals; scrambles remain rushing, unlike Deck's NFL dropbacks |
| Pass rush and protection | Box scores supply sacks and sacks allowed | Counts were reconciled across tables, not independently reconstructed from plays |
| Opponent-strength context | Current opposing-facet means, opponent ranks, counts, and game logs can be calculated locally | These are descriptive context, not recursively adjusted ratings or an overall SoS rank |
| Spread and history | BYU–UCF identity, kickoff, contract rules, quote, and hourly history verified | One matchup proves the integration path, not universal market availability |
| Injuries, depth, blitz/man-zone | No comprehensive free all-FBS source verified | Omit from v1 unless a dependable source is established |

Primary sources: [SportsDataverse datasets](https://github.com/sportsdataverse/cfbfastR-cfb-data/blob/main/DATASETS.md), [public data releases](https://github.com/sportsdataverse/sportsdataverse-data/releases), [analytics definitions](https://py.sportsdataverse.org/docs/reference/python-helpers/analytics), and [ESPN endpoint wrapper documentation](https://py.sportsdataverse.org/docs/cfb/reference/additional/highlights). Exact fetched URLs, timestamps, hashes, and columns are saved in the evidence JSON files below.

[CollegeFootballData](https://collegefootballdata.com/api-tiers) is an alternative: its published free tier offers 1,000 calls/month and requires a key. It was not authenticated or tested in this audit. Paid opponent-adjusted/live products should not become dependencies. Published SportsDataverse ratings are another research option, not a validated requirement.

## What the checks established

- The saved source contains 138 source-classified FBS teams. This classification has not been independently checked against authoritative membership, including transitional teams.
- All four statistics tables contain the same 1,020 team-game keys covering 510 completed FBS-participant games, with no duplicates or omissions relative to the saved schedule. Restricting to FBS-versus-FBS leaves 388 games.
- The statistics assets were updated October 18 and include games through October 17 Eastern time. The current schedule feed exposed **12 newer finals** absent from that snapshot. Fresh kickoff information does not repair stale rankings.
- Independent recomputation matched all 828 team/facet values and 828 competition ranks in each scope. It also matched 4,656 FBS-only and 5,388 inclusive game/facet values. This verifies arithmetic, not the upstream accuracy of every play.
- One supporting box-score discrepancy remains: Air Force, game `401864516`, has −6 net passing yards on one attempt but a published yards-per-pass value of 0.0. The preview uses explicitly labeled net passing yards/attempt calculated from the counts. The other 1,019 rows reconcile within rounding tolerance.
- Passing and rushing EPA are equal-weight means of the published game values, consistent with Deck's game weighting. Their rounding, scramble treatment, and unverified play filters prevent claiming exact NFL methodological parity. Passing/rushing touchdown totals are unavailable in the selected tables and remain missing.

Evidence: [statistics](stats-audit.json), [schedule reconciliation](schedule-feed-audit.json), [independent review](independent-review.json), [market verification](market-audit.json), [all computed rankings](rankings.json).

## Real matchup preview

The saved preview uses BYU at UCF, October 24 at 3:30 PM Eastern. ESPN game `401856835` was matched to Kalshi event `KXNCAAFSPREAD-26OCT24BYUUCF` using team metadata and kickoff, rather than ticker text alone. The bulk schedule's placeholder time was unsuitable for matching.

Deck's existing default-spread function selected BYU −7.5 from 31 contracts. Its saved Yes ask was 48¢ before fees at approximately 12:02 PM Eastern. The history contains 137 hourly midpoint observations and retains one missing interior hour. These are saved observations, not live prices or a recommendation.

The preview preserves the six paired categories, same/opposing-unit toggle, supporting statistics, clickable game logs, and dark appearance. Opponent context is expanded by default. It has no trade, watchlist, or database writes.

### FCS treatment needs one explicit decision

The user has ruled out displaying FCS team statistics. Both preview scopes honor that: FCS opponents receive no season metrics or rankings. The unresolved question is whether **the FBS team's performance against FCS** counts toward its own rankings.

This materially changes the sample: including those performances moves BYU's rushing offense from 10th to 4th and UCF's from 125th to 100th. The preview includes both scopes for comparison; its initial FBS-only selection is not a settled product decision.

For context, the FBS rushing defenses BYU faced average +0.049 EPA allowed per rush, versus −0.056 for UCF's opponents. Lower is stronger defense. This comparison is the mean of each opponent's current season metric per meeting, includes head-to-head games, and is not an opponent-adjusted assessment of BYU or UCF.

## Recommended implementation sequence

1. Resolve the FCS counting rule using the preview. Confirm the six-category layout and prominent opponent context.
2. Audit raw play data or another free source to resolve EPA precision, scramble classification, filters, and update latency. Establish completeness checks against current schedules and an authoritative FBS membership list.
3. Add sport-scoped identities, caches, snapshots, routes, and source adapters; then connect the existing interface. Show explicit as-of times, missing coverage, and unavailable markets.
4. Validate multiple weeks and varied matchups, including FBS–FCS, neutral sites, postponements, missing markets, and stale feeds, before enabling the tab.

## Reproduction and validation

The scripts use Python's standard library. `fetch_sources.py` downloads five current public CSV assets to `/tmp/deck-cfb-audit`; `audit_stats.py` rebuilds the statistics outputs from that cache. Releases can change, so a fresh download will not necessarily reproduce this captured snapshot. The hashes in `stats-audit.json` identify the audited inputs.

`audit_market.py` requires cached `kalshi-*.json` responses from the URLs listed in its `SOURCES` mapping and the saved schedule audit. It reuses the existing app's pure quote-selection/history functions. `build_preview.py` combines the saved outputs, template, and cached BYU/UCF logo WebPs. The generated preview embeds its data and images and requires no runtime data requests. Schedule and independent-review JSON are captured audit evidence, not standalone fetch scripts.

Validation covered Python syntax, JSON parsing, arithmetic reconciliation, selected-contract identity/rules, and browser interactions: scope switching, same-unit mode, game-log opening/closing, focus return, FCS field suppression, and desktop/360-pixel layouts. Full application tests were not run because no application code changed.
