Deck Project:

Build a GUI that contains a variety of information about nfl spreads. Pull the sportsbook data from kalshi and research options for the neccessary stats, advanced stats, depth charts, and rankings. The info I would like included is as follows:

1. spreads and if possible the graph of the history of the percentages at that spread on Kalshi
2. man vs zone & blitz percentage
3. questionable/doubtful/out players
4. rankings for each team (passing offense vs passing defense, running offense vs running defense, etc)
5. pff grades if free and possible
6. available player props on kalshi
7. for each player, there should be a game log of past performances. those game logs should also contain their opponents ranking for that particular field. (ie if a player is a receiver, their game logs should show their opponents passing defense ranking)
8. bet tracker: I can place any available bet, (if calculating fees is a problem, i can simply enter what I put in and what it pays out) and it keeps track of each bet. There should be a modifiable unit size too so it can show how many units i'm up/down. make sure its added that if we go the noncalculating way units won't be round because sometimes I put in a $10 bet and it only does $9.99, so i bet .999 units instead of 1. find a way to account for this. There also needs to be a combo/parlay feature. 
9. might want to add rankings and stats for receiving yards to rb, rushing yards to qb, etc, especially when looking at a player prop they concern.
10. Create an Elo rating system for NFL teams where each team has a strength rating that updates after every game. Teams gain points for wins and lose points for losses, with bigger changes for upsets and smaller changes for expected results. Account for opponent strength and home-field advantage, and use rating differences to estimate win probabilities.&#x20;



This is just the start. If there are any features that could be interesting for my betting purposes or simply cool, give me those suggestions. 

GUI:
the gui should feel modern, clean, and interactive. The main screen should have all of the games in the given week (that haven't happened yet), with just the spread and the graphs if that's a viable feature. clicking that game should provide the user with features 2-5. then have a second tab for the player props part. clicking on one of the player props should open their game log. ensure I can toggle the player props (ie 30+, 40+, 50+ receiving yards) Make sure the team logos are included so it feels complete.

## Agreed requirements from project discussion

These decisions clarify the original brief above. Items marked unresolved are not approved implementation choices.

### Collaboration and scope

- The user is the engineering decision-maker. Present concerns, options, and recommendations before making engineering decisions or implementing them.
- This is a personal, desktop-focused browser app that the user can install through the browser. Phone access is not required.
- Run locally on the user's computer for now, with no hosted deployment. A local service runs while the app is in use; data refreshes still require internet access.
- Approved stack: React and TypeScript with Vite for the browser interface, Python with FastAPI for the local backend, and SQLite for local storage. For ordinary use, one startup command runs the Python service, which serves both the built interface and its data on localhost.
- Research and recording bets placed elsewhere only for now. Leave room for future trading support, but do not implement order placement now.
- Manual refresh is sufficient.
- Prefer free sources. Discuss unavailable data, paid alternatives, or feature substitutions with the user.
- Avoid PFF for now, including its paid API. PFF grades are not part of the current implementation; the statistical rankings below are not replacements for PFF film grades.
- The rest of the requested feature set remains in scope. Data problems require discussion rather than silent omissions.

### Navigation and market selection

- The home screen shows games in the selected week that have not started.
- Each game initially shows the available spread closest to 50/50 odds and that contract's probability history where available.
- Choose the default spread by its bid/ask midpoint's distance from 50%, and show actual quoted prices alongside that indicative midpoint. Break equal-distance ties by the narrower bid/ask gap, then higher trading volume. Contracts without valid quotes on both sides remain selectable but cannot be the default.
- Matchup details allow selection among the available spreads.
- Match Kalshi public game/team metadata to nflverse by season, week, designated home/away teams and exact kickoff time after timezone conversion. Use explicit known aliases (JAC → JAX, LAR → LA). Flag missing or conflicting information for review.
- Keep upcoming scheduled games visible with "Spread unavailable" when contracts cannot be matched confidently. Validate the contract's participant and threshold before showing its prices; display conventional notation such as SEA −2.5 with the original contract wording available to inspect.
- Use nflverse kickoff to hide started games. Kalshi contract closing time is not kickoff. Cache and manually refresh the additional Kalshi game/team records using the existing snapshot approach.
- The player-props tab lives inside each matchup and is limited to that game.
- Allow selection among each player's available prop thresholds, such as 30+, 40+, and 50+ receiving yards.
- Selecting a player prop opens that player's current-season game log.
- Game logs show the opponent's current relevant ranking, not its historical ranking at the time of the game.

### Spread-history charts

- Plot the historical YES bid/ask closing midpoint, consistent with the displayed spread midpoint. Use hourly points, a seven-day default, 24-hour and six-hour alternatives, and a fixed 0–100% scale.
- Missing hours and missing or invalid two-sided quotes break the line. Do not substitute trade prices, carry prices forward, or invent history before a market has data. Use the same valid-quote rules as current midpoint selection.
- Load history automatically once per displayed contract per page session (updated user direction, October 16). Keep Refresh lines and individual detail refresh controls for explicit updates/retries. Fetch histories sequentially; remounts reuse successful or failed attempts without retry loops. Do not poll automatically or couple history downloads to source-snapshot refreshes.
- Keep downloaded history in memory while the page is open, including across navigation. Switching ranges reuses the seven-day download. Refresh failures preserve the previous chart and expose the error and attempt time; show the successful fetch time and requested window. Reloading the page clears history memory.
- Charts support pointer/keyboard inspection of hourly values. Selected-spread details also expose an hourly quote table and source link. Newly listed markets may have less than seven days of data.

### Player-prop matching and initial coverage

- Match Kalshi players to nflverse only when the exact player name and canonical team identify one NFL player ID and the position agrees. Flag missing, ambiguous or conflicting matches for review instead of guessing. Once matched, follow the NFL player ID across current-season games, including games for a previous team.
- Initially support passing, rushing and receiving yards; receptions; passing touchdowns; passing attempts and completions; interceptions thrown; rushing attempts; and combined rushing/receiving yards. Other linked market types remain explicitly listed as not yet supported while their rules and game-log needs are investigated. This staged implementation does not remove them from the overall requested scope.
- For combined rushing/receiving yards, show both the opponent's current rushing-defense and passing-defense ranks separately. Do not invent a combined ranking.
- Validate game links, player/team identities, threshold and settlement wording before displaying a contract. Preserve the original primary and secondary rules for inspection.
- Player game logs use official current-season regular-season statistics, including overtime. Missing player-game rows are not invented as zero or labeled as confirmed DNPs; unavailable statistic values remain unavailable. Official rushing statistics include scrambles and kneeldowns, unlike the designed-run EPA ranking.

### Bet tracker

- Record bets placed on Kalshi; "place" in the original tracker brief means recording, not submitting real orders through this app.
- Allow an editable default unit size. Preserve the unit size used for each recorded bet; changing the default affects new bets and does not recalculate historical results using the new size.
- Preserve fractional units based on the actual amount paid. For example, $9.99 paid with a $10 unit size is 0.999 units wagered, not 1 unit. Use the bet's preserved unit size when expressing its profit/loss in units.
- Initially represent a combo/parlay as one ticket with multiple legs, one actual total cost, and one combined payout. Track the ticket's actual payout rather than deriving it by multiplying individual leg prices.
- Enter actual total cost including fees, optional potential total payout, and actual total returned when closing a ticket. Payout/returned amounts include the stake: $10 paid and $25 returned means +$15. Open tickets show stake separately and are excluded from realized profit/loss.
- Start with whole-ticket records: enter one final total received after the entire bet is sold or settled. Do not track individual partial sales or additional purchases separately in this version.
- Store permanent tracker records in separate tables in the existing local SQLite database, using exact money arithmetic. Records survive source refreshes and season changes. Include export/import backups.
- The whole-ticket tracker is implemented. Record singles or multi-leg combos, including manual descriptions for markets not yet supported in research views. Spread/prop views can pass a selection into the tracker; the user still enters the chosen side and actual amounts.
- Ticket editing and closing are available; reopening clears realized results until a new final return is entered. Saved unit sizes remain fixed. Unit totals sum each ticket's result divided by its own original unit size. Displays round units to six decimal places only when needed, marked with ≈; calculations retain exact values.
- Export/import uses a versioned JSON backup of all tickets and the default unit size. Imports add missing records, skip identical records, and reject conflicting records without partially importing. An existing default unit size is preserved; an unset default can be restored from the backup.

### Rankings and supporting statistics

- Use current-season regular-season games, including overtime. Exclude preseason and playoffs for now; postseason behavior will be discussed separately.
- Show one headline rank per category, with supporting statistics underneath.
- Show league mean and median alongside each ranking metric's direction label ("Higher is better" / "Lower is better"), including blitz frequency. Give each available team's season value equal weight, exclude unavailable values, and flag incomplete coverage. In the final GUI, make these small, secondary text to preserve the minimal, modern design.
- The four main rankings measure overall football effectiveness, rather than prop-specific matchup favorability.
- Each ranking, including pass rush and pass protection, opens a team game log when clicked.
- Use the following initially approved formulas and supporting statistics:

| Category | Headline measure | Supporting statistics |
| --- | --- | --- |
| Passing offense | EPA per dropback, highest first | Passing yards/game, yards/attempt, completion percentage, touchdowns, interceptions |
| Passing defense | EPA allowed per dropback, lowest first | Passing yards allowed/game, yards/attempt allowed, completion percentage allowed, touchdowns allowed, interceptions |
| Rushing offense | EPA per designed run, highest first | Rushing yards/game, yards/carry, rushing touchdowns, success rate |
| Rushing defense | EPA allowed per designed run, lowest first | Rushing yards allowed/game, yards/carry allowed, rushing touchdowns allowed, success rate allowed |
| Pass rush | Sacks/game, highest first | Opponents' average sacks allowed/game |
| Pass protection | Sacks allowed/game, lowest first | Opponents' average sacks/game |

- For the four EPA rankings, calculate efficiency separately for each game and average the game values equally. Do not pool plays across games or give recent games extra weight.
- Count sacks and quarterback scrambles as dropbacks for efficiency calculations. Exclude kneeldowns and spikes. Ordinary yardage statistics retain their official definitions.
- Initially, do not adjust the headline ranks for opponent strength. Opponent rankings in game logs provide context.
- The same current headline rankings supply the opponent-ranking context in player game logs.
- Rushing success means positive EPA on a designed run. Calculate each game's success percentage and average game percentages equally.
- For EPA and rushing success, include penalty outcomes classified by nflverse as pass or run. Exclude unclassifiable penalties and two-point attempts.
- Exclude missing values from the affected calculation and report coverage. Games without usable plays are unavailable, omitted from that metric's season average, and cause an incomplete flag. Teams without usable games are unranked.
- Rank unrounded values, with exact ties sharing a competition rank (1, 2, 2, 4).
- Supporting touchdowns and interceptions are season totals. Completion percentage and yards per attempt/carry use season totals, while EPA, rushing success, and blitz rates retain equal game weighting.

### Position-specific defensive context

- Initially show five categories: receiving yards allowed to RB/FB, WR and TE; rushing yards allowed to RB/FB and QB. Fullbacks are grouped with running backs and explicitly labeled RB/FB. Use the position supplied in each player-game row, rather than applying today's position to earlier games.
- Headline ranks use yards allowed per completed team game, with #1 meaning fewest allowed. Every verified game counts equally, including verified zeroes. Keep exact competition ties, current-season regular-season scope including overtime, and equally weighted team-season league mean/median.
- These are totals against an entire position group, not predictions of one player's performance. No opponent-strength adjustment or minimum-game cutoff in this version; expose game coverage and opportunity counts.
- Receiving support: targets/game, total targets, receptions/game, yards/target and total receiving touchdowns allowed. Rushing support: carries/game, total carries, yards/carry and total rushing touchdowns allowed. Efficiency ratios divide season totals; no opportunities means the ratio is unavailable.
- QB rushing headlines use official rushing totals including designed runs, scrambles and kneeldowns. Show each component's yards/game separately only for games where every QB's play-by-play yards and attempts reconcile with official player totals. An unavailable breakdown does not remove verified official totals. Component coverage can differ from headline coverage and must be visible.
- Verify player statistics against official team totals and the completed schedule before treating absent position contributions as zero. Exclude and flag missing, duplicate or conflicting records; do not silently fill missing games with zero. Independent missing touchdown fields may leave verified yardage available.
- Approved data exception: exclude rows with no name, player ID or position only when all seven relevant rushing/receiving fields are explicitly zero. Report the exclusion and still reconcile team totals. Unidentified rows with missing or nonzero relevant values make the affected game unavailable.
- Keep overall defensive rankings alongside position-specific ranks in prop views and player game logs. Both open team game logs. Use current opponent ranks; for combined rushing/receiving props, show the applicable receiving and rushing ranks separately, without inventing a combined rank. Unsupported position/statistic combinations keep the existing overall context.
- These calculations reuse saved nflverse player statistics, team statistics, play-by-play and schedules; no new data subscription or refresh source is needed.

### Blitz rate

- Label the metric "FTN-charted blitz rate." A blitz is a play where FTN records at least one blitzer; do not substitute a threshold on total pass rushers.
- Calculate each game's percentage of charted dropbacks with a blitz, then average game percentages equally.
- Rank blitz frequency with #1 meaning most frequent, not most effective. Use exact competition ties and the existing incomplete-data rules; no usable charting means unranked. The displayed rank opens the blitz game log.
- Exclude nullified plays and two-point attempts, as well as kneeldowns and spikes. Flag missing charting rather than interpreting it as zero blitzes; apply the approved missing-data and zero-denominator rules above.

### Sack comparisons and game logs

- Average the current-season per-game rates of opponents already faced, counting each matchup once. Repeat opponents therefore count once for each meeting; future opponents do not enter the average.
- Opponents' season averages include their head-to-head games against the team being evaluated.
- Each pass-rush game-log row shows sacks recorded in that game alongside the opponent's current-season average sacks allowed/game.
- Each pass-protection game-log row shows sacks allowed in that game alongside the opponent's current-season average sacks/game.

### Approved data sources

- Kalshi public API for spreads, player props, and price history.
- Public Kalshi player identities, with the same manual snapshot caching and refresh-failure reporting as game/team identities, support the approved exact player matching.
- nflverse for schedules, player/team statistics, play-by-play ranking inputs, and depth charts.
- FTN charting via nflverse for the approved blitz-rate calculation above.
- Sharp Football's public coverage table for man/zone rates. Show the source and update information, and clearly identify stale or unavailable data. Its statistical cutoff is not explicitly stated, and webpage changes may break retrieval.
- Official NFL injury reports for injuries, because they were fresher than the nflverse injury snapshot during the source audit.
- The user confirmed that local startup works.
- Cache each source's latest validated snapshot in SQLite. Retain the previous snapshot when refreshing fails, and expose its fetch timestamp and refresh error. Price history continues to come from Kalshi.

### Implementation checkpoint

- Source readers, SQLite snapshots, manual-refresh controls, and source timestamps/errors are implemented. The current source-status screen is temporary, not the final matchup design.
- The user confirmed the refresh-controls checkpoint after the source integration.
- The six approved team rankings, supporting stats, FTN-charted blitz rates, league mean/median context, and team game logs are implemented in the backend and interim browser interface. Game logs include opponents' current corresponding ranks and sack-rate context.
- Verified game-to-market matching and a basic weekly matchup view are implemented, including logos, default/alternate spreads, both teams' ranking comparisons, coverage, injuries and depth charts. Final visual design remains unfinished.
- Kalshi game/team metadata use the existing manual snapshot cache. Game identities are resolved from cached spread events; refresh spreads before game identities. Kalshi's non-team "Retires / No Team" placeholder is excluded and reported in source status.
- The matchup now includes a player-props view for the ten approved initial categories, selectable thresholds, actual saved quotes, original settlement rules, and clickable current-season player game logs with opponents' current ranks. The source catalog now contains 22 datasets. Other market types linked by Kalshi game metadata are listed explicitly as not yet supported; linked events do not guarantee currently open contracts.
- Validation passed: 13 automated source/cache/selection tests, TypeScript and production build, live refreshes of all 13 configured datasets into a temporary database, and local HTTP checks including preservation of cached data after a simulated source outage. Browser visual inspection was unavailable.
- Ranking validation: 12 additional calculation tests (25 total), TypeScript/build, and an integration check using downloaded data for 32 teams, 79 completed games and 158 team-game logs. The local API was checked with empty caches, different seasons, and simulated refresh failure. Browser visual inspection remains unavailable.
- Matchup checkpoint validation: all 43 current tests and the production build pass. Local HTTP checks verified 14 games and 359 contracts, team logos/research, unavailable identities, past/future week filtering and preservation after refresh failure. Browser control was unavailable, so visual verification remains outstanding.
- Player-prop checkpoint validation: all 63 tests and the production build pass. The downloaded-data audit verified 1,752 contracts in the ten supported categories, 136 uniquely matched players, and 233 player/statistic groups across 14 games. Those groups produced 1,091 game-log rows with current opponent ranks and no matching or log-validation issues. Disposable-database HTTP checks verified the new endpoints, all 22 source entries, combined-yardage ranks, wrong-season and unknown-player handling, and preservation after a simulated player-identity refresh failure. Browser visual verification remains unavailable. Evidence: docs/player-prop-mapping-audit.json.
- Tracker checkpoint: permanent tracker/settings tables, exact accounting, singles and combos, editing/closing, spread/prop entry shortcuts, and export/import are implemented. All 81 tests, TypeScript/production build and disposable-database HTTP checks pass, including fractional units, historical unit preservation, mixed-unit totals, duplicate-save protection, stale-edit rejection, atomic backup imports, source-cache isolation, server restart persistence and restoration into a fresh database. Browser visual verification remains unavailable. Evidence: docs/tracker-validation.json.
- Spread-history checkpoint: charts are implemented on weekly default-spread cards and selected-spread details. Validation passed: 87 Python tests, four frontend history checks, TypeScript/production build, three public Kalshi history downloads, and disposable-database HTTP checks. Tests cover quote-only midpoints, missing periods, range switching, request sequencing, duplicate-load prevention and retention after failed refreshes. Browser visual verification remains unavailable. Evidence: docs/history-validation.json.
- The user confirmed the spread-history checkpoint.
- Position-specific defense checkpoint: all five approved categories, supporting stats, QB rushing components, league mean/median and clickable team logs are implemented. Team research, upcoming prop opponents and historical player logs show the relevant position ranks alongside existing overall rankings. Validation passed: 103 Python tests, TypeScript/production build and disposable-database HTTP checks across 32 teams, 79 completed games and 14 upcoming matchups. The downloaded data yields 160 complete headline rankings and 158 verified QB game breakdowns. Five unidentified zero-contribution rows are excluded with notices under the approved rule. Of 233 verified player/stat groups, 174 receive position context. Visual browser verification remains unavailable. Evidence: docs/position-defense-validation.json.

### Elo — approved model and backend checkpoint

- Elo is an explicit exception to the current-season-only statistical rankings. Replay regular-season and playoff games from 2002 onward, starting all 32 franchises at 1500. Exclude preseason and preserve franchise continuity across OAK/LV, STL/LA and SD/LAC relocations.
- Include winning margin using the FiveThirtyEight diminishing-margin formula and opponent-strength correction. Use the conventional 400-point logistic scale. Neutral-site games receive no home advantage.
- Approved initial settings: K=20, home advantage=50 Elo points, and two-thirds offseason retention toward 1500. Apply regression once per season; a 1600 rating becomes approximately 1566.7 before the next season.
- Settings were selected from 120 candidates using 2007–2021 after a 2002–2006 warmup. Hold out 2022–2025 for validation; exclude 2026 from selection. The selected configuration's held-out expected-score cross entropy was 0.63551 versus 0.63798 for the published-parameter baseline. This modest improvement does not establish betting profitability. Evidence: docs/elo-parameter-comparison.json.
- Count ties as half a win. Label outputs "Elo expected score: P(win) + 0.5 × P(tie)." They are not exact outright-win probabilities or spread-cover probabilities. Historical game expectations use ratings before that result; upcoming games use the latest saved ratings, without simulating intervening games.
- Keep a separate "Elo game history" snapshot in SQLite, using the free nflverse schedule and existing refresh/failure reporting. Each selected-season cache contains 2002 through that season. Replay from saved results to handle corrections and avoid counting a game twice. The source catalog now contains 23 datasets.
- Approved completion convention: kickoff is past and both valid scores are published by nflverse. The source has no explicit final-status field; disclose that limitation. Unscored started games remain flagged and do not update Elo. Invalid or conflicting history fails validation and preserves the previous snapshot. Validation cannot independently detect every game omitted upstream.
- Backend implementation provides /api/elo?season=2026 with ratings, exact competition ranks, league mean/median, season-start ratings, changes, current-season game logs, matchup expected scores and source provenance. Missing snapshots return an explicit unavailable state.
- The Elo agent owns backend calculations, tests and documentation; the separate GUI agent owns placement and presentation. Handoff: docs/elo-api.json. No Elo GUI layout or presentation decisions were made here.
- Validation passed: 123 Python tests and disposable-database HTTP checks. The audited schedule replays 6,578 completed games and produces 32 team ratings, 79 current-season game results and 193 upcoming matchups. Verified score corrections, repeat reads, offseason regression, neutral sites, ties, cache failure retention and persistence. Evidence: docs/elo-validation.json.

### Final GUI direction — agreed during design interview

- Use dark mode and Inter. The visual reference is Raycast, toned down: minimal, smooth, responsive and interactive. TradingView's density is explicitly unwanted. Exact colors, surfaces and motion details remain to be settled.
- The home screen shows compact game cards in a grid grouped by day. Show each default spread with a small history line, without visible axes, chart background or grid. The matchup detail view is less minimal and exposes fuller information. Existing history-data rules still apply; lines now load automatically per the October 16 update.
- Clicking a game opens a dedicated matchup page with Stats and Player Props tabs. Wide screens include a narrow, collapsible sidebar listing the week's games grouped by day. A Back to games control returns to the full grid. Switching matchups preserves the active Stats/Player Props tab.
- The primary display is a 27-inch monitor, but layouts must respond down to phone widths. Reduce grid columns on narrower screens, replace the game sidebar with a game-switcher button, and allow statistical tables to scroll horizontally. This supersedes the earlier exclusion of phone-width interface support; access from a separate phone remains a separate, unresolved decision.
- Prefer compact dropdown menus to reduce visual clutter. Which information stays visible versus opens through controls remains to be decided.
- Team-color accents are under consideration, not yet a finalized palette or placement decision.
- Continue the design interview through clickable visual previews as soon as there is something concrete to show. Let the user inspect each preview before asking further design questions. Preview data must be clearly labeled as illustrative; it is not live market or performance data.
- Home cards show the selected spread's ask price; omit bids and bid/ask pairs. Label the chosen side and price clearly. An ask is a quoted entry price before fees, not a guarantee of an entire order's eventual fill price. Default-spread selection remains based on the approved midpoint rules. Historical midpoint lines remain distinct from the displayed current ask; changing the history measure has not been approved.
- Team comparisons include a toggle between opposing units (e.g. passing offense vs passing defense) and like-for-like units (e.g. passing offense vs passing offense).
- Player and team game logs open in a wide desktop overlay and a full-screen view on small screens, returning to the previous research position when closed. Player logs retain the selected prop/threshold and distinguish results that meet it.
- Refresh on open is implemented: show saved content immediately, refresh sources sequentially once on opening for the selected season, then update displayed reports. Manual refresh remains available afterward. No polling; history loads automatically when shown and is independent of source refreshes. Failed reads/refreshes preserve saved content with visible notices; invalid-data responses clear unusable results.
- The first clickable GUI preview explores the home grid, matchup navigation, comparison modes, statistic-first prop browsing, threshold dropdowns and game-log overlays. Prop browsing and the preview's detailed visual choices are proposals awaiting user feedback. Production interface/backend behavior has not yet been replaced by the preview.
- The user likes the first preview and accepts it as the visual baseline, requesting a more responsive interaction feel. Refine immediate hover/press feedback, navigation and selection transitions, dropdowns, and game-log overlays while retaining that layout. Respect reduced-motion preferences.
- Extend the card treatment into matchup details: the user prefers the clean card appearance for props and related content. The updated preview uses individual player-prop cards, paired team-comparison cards, and expandable supporting-information cards. Exact card density remains subject to visual feedback.
- Keep statistical context attached to the item it explains. Each prop card includes its upcoming opponent's relevant overall and supported position-specific defensive context. Each comparison card expands to show the supporting statistics for its two selected team/category combinations. League mean/median and direction labels appear as small secondary text beside their corresponding metrics. Remove the disconnected opponent-context and supporting-statistics/league-average panels from the preview. Preview values remain illustrative until the production data connection is implemented.
- Elo GUI integration uses docs/elo-api.json. The live matchup cards and details display backend team ratings, ranks, last-game changes and correctly labeled Elo expected scores. Clicking a team opens its current-season Elo history. Source freshness, refresh errors and the published-score completion limitation remain accessible. No frontend Elo calculation or default substitute ratings.
- The design preview shows compact nested Elo cards with clickable histories from a dated October 15, 2026 API snapshot. The preview's matchups and market/statistical fixtures remain illustrative; no Elo matchup expectations are assigned to those fictional game identities. The live app reads /api/elo and updates after source refreshes.
- Supporting-stat expansions retain two aligned columns beneath the same teams as the headline comparison, including aligned labels/values across rows. Preserve the dropdown animation. Player-prop menus anchor inward and adjust to the available screen width and height.
- The user approved the current visual direction and authorized proceeding. The design is now implemented in the live React app: dark surfaces and locally hosted Inter, responsive day-grouped game cards, ask-only primary prices, axis-free history lines, hash-based dedicated game pages with browser Back, a collapsible desktop sidebar and mobile game switcher, opposing/same-unit comparison cards, prop cards with per-group threshold retention and attached opponent context, and team/player/Elo log overlays. Elo and other displayed data come from the existing APIs; no preview fixtures are used in production.
- Supporting comparisons use the backend's values, coverage and headline league summaries; no placeholder support-stat averages are carried over from the preview. All ten supported prop categories, source/matching notices, position defenses, coverage/injuries/depth and tracker entry points remain available. Tracker accounting/storage and Elo calculations were not changed.
- Live GUI verification: TypeScript/build and 123 backend tests passed. Frontend checks cover history rules, Elo joins and saved-report request deduplication, revision ordering, failure retention and season isolation. A DOM interaction run with actual saved API fixtures verified 14 home games, one sequential 23-source opening refresh, dedicated navigation, comparison modes, paired supporting rows, threshold persistence, opponent-log return, modal focus restoration, Elo histories and tracker access. Browser visual verification remains unavailable.
- Installation checkpoint: the user authorized browser testing and app installation/startup work. The built app now has a standalone manifest, K icons, and an install control under Data when the browser offers installation. Its service worker only caches a service-stopped recovery page; API data and tracker writes are never cached or queued. The installed shortcut still requires the foreground local service; no OS autostart or background daemon was added. Startup skips unchanged builds, reuses a healthy existing app, and refuses unrelated/unhealthy port occupants. TypeScript/build, 127 backend/startup tests, frontend checks, HTTP asset checks and a simulated install-control flow passed. Actual browser installation and visual verification remain pending: the browser inventory was empty and opening an in-app browser returned unavailable.

### Watchlist and threshold comparisons (October 16)

- Add a Watchlist tab for specific spread and player-prop thresholds across games. Save bookmarks permanently in SQLite; keep them through refreshes and season changes. Read quotes from verified current snapshots, retain unavailable bookmarks for removal, and reopen the exact saved selection.
- Watchlist entries support editable notes and a Yes/No side, with no side assumed for existing bookmarks. Save both permanently; show the chosen side's actual ask and carry the saved side/notes into tracker drafts. Keep unsaved edits across in-app navigation and reject stale edits from another tab. Threshold comparison tables remain Yes-ask only.
- Present watchlist entries as minimal, responsive cards with the contract, saved side, ask, and a short notes preview. Adding a watch or selecting Edit details opens a compact popup for side and notes. Successful saves close it; closing without saving keeps the session draft. Keep inline inputs off the cards.
- Match the watchlist card design to player-prop cards: share their grid, team accents and verified logos, heading hierarchy, threshold/ask layout, spacing, and footer action styling. Preserve the side/notes popup.
- Keep prop threshold comparisons minimal: threshold and Yes ask. Selecting a row changes the active contract for watching, recording and game-log inspection.
- In player game logs, show hits / games with a verified statistic for every available threshold. Count values at or above the threshold, include verified zeroes, exclude missing values, and show unavailable when there are no usable games. Preserve the existing current-season regular-season scope.

### Still unresolved

- Broader player-prop support beyond the approved first ten categories, final browser visual verification, and verification of the native browser installation/recovery flow. Installation support itself is implemented.
- Ongoing source completeness and freshness checks; see docs/data-source-audit.json for the initial verification.
- The broader prop audit found first-touchdown, longest-play, fantasy, variable-payout, head-to-head and other linked markets that need separate support. The broader identity audit also found an unmatched player and a position disagreement outside the ten supported categories. Details are in docs/player-prop-mapping-audit.json; do not silently substitute statistics or guess identities.
- Game matching audit: docs/matchup-mapping-audit.json records 14 uniquely matched spread events and 359 consistent contracts, using public Kalshi milestones/team targets and the nflverse schedule. Kickoff times agreed for all audited games. The matching rules above are approved.
- Game and initial player matching, midpoint selection, tie-breaking, missing-quote behavior and spread-history rules are approved. Future exact player-match failures require review rather than fuzzy matching.

- October 16 visual refinement: home-card sparklines show only the line, without the “Midpoint · 7D” caption or a load button. Description, fetch time and error context remain in accessible labels/tooltips and matchup details. Team-inspired accents appear on game cards, line gradients, Elo tiles, paired comparison columns and player-prop cards; data text stays neutral.


### Hosted Deck proposal from October 16 2026 — superseded

The product is branded **Deck**, using the supplied logos in `public/icons`. The
planned address is `deck.getwellsedge.com` on the existing Vegas EC2 server.
Public users must have separate accounts and require administrator approval.
These hosted requirements supersede the earlier local-only access scope; existing
single-user storage is not yet suitable for public access. Preserve the current
interface feel while adding secure identity, private records and bounded shared
research computation. The audit and phased rollout are recorded in
`docs/deployment-audit.md`. Infrastructure changes and production exposure have
not been performed as part of deployment preparation.

### Packaged desktop proposal from October 16 2026 — superseded by Git updates

- Replace the hosted proposal with standalone Deck installers for Windows x64,
  macOS Intel and Apple Silicon, and Linux x64. Each person has a separate local
  database. End users should launch an app icon without Bash, Git, Python, or Node.
- Install once and receive automatic updates. Keep personal data outside the
  installation directory, back up before version upgrades, and ask before
  restarting to install a downloaded update so unsaved edits are not lost silently.
- Source remains `timcocuzza/kal-deck`. Do not transfer it to wellstechadvisorsllc.
  A public installer-only repository under timcocuzza is proposed if source stays
  private; the release repository has not been created or confirmed.
- Apple Developer signing may already be available; Windows signing is not yet
  set up. Preview builds can be unsigned, but the production workflow must require
  Mac signing/notarization and Windows publisher verification. Never embed GitHub
  tokens or signing credentials in distributed apps.
- Preserve the current visual feel and use the supplied Deck branding. Technical
  data-quality details belong in collapsed disclosures. Keep unavailable/incomplete
  metrics and actual refresh failures visible beside the affected data.
- The six unidentified zero-contribution row notices were checked against the
  current saved 2026 data: 80 completed games, six benign skips, no reconciliation
  failures and no incomplete position-defense headlines. This is a snapshot result,
  not permission to skip validation on future downloads.
- Implementation and release gates are documented in `docs/desktop.md`.

### Current desktop direction with Git updates

- The user chose a Git-backed desktop launcher to avoid annual Apple signing costs
  and is willing to make `timcocuzza/kal-deck` public. Do not change visibility on
  their behalf without explicit authorization to publish it.
- One-time setup may require Git, Node and Python. Everyday launching and updates
  must use a normal app icon and an Update Deck control without terminal commands.
- Build each candidate in an isolated managed checkout/environment. Keep the
  current app usable during preparation, verify the candidate before switching,
  preserve the previous version and personal records, and prompt before restarting.
- Identify updates and database backups by Git revision, including commits that
  retain the same package version. Personal data stays outside managed code.
- Keep the existing interface and private local backend. Replace the certificate
  release workflow with native source-install validation on all four targets.
- Follow `docs/desktop.md` for the current setup and maintenance flow. The old signed
  installer plan and its validation results are historical and no longer the default.
