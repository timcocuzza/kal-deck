# Deck

Personal NFL and Kalshi research app for **Windows, macOS and Linux**. Install Git,
Node.js 24 (or 26), and Python 3.14 once, then run `python scripts/install_desktop.py`
from a clean checkout. Open the **Deck** app icon for everyday use. **Data → Update
Deck** builds and checks new Git revisions before offering a restart. Each person's
records stay on their computer; no terminal is needed for normal use or updates.

The [desktop setup guide](docs/desktop.md) covers Mac/Windows/Linux installation,
updates, security, resources and CI. This source-based approach requires no Apple
Developer membership or Windows signing account. Native Mac and Windows GUI
acceptance is still pending. Source stays at `timcocuzza/kal-deck`; the public HTTPS
repository is the update channel. Repository visibility has not been changed here.

The earlier [Vegas deployment audit](docs/deployment-audit.md) is retained as history.
Public web hosting and administrator-approved accounts are superseded by the
desktop direction. Product requirements are in [instructions.md](instructions.md).

## Current status

The approved dark, Inter-based layout is now the live interface: games grouped by
day, compact ask-price/history cards, dedicated Stats and Player Props pages,
paired team comparisons, threshold dropdowns and game-log overlays. Browser Back
returns through matchup navigation; wide screens include a collapsible game sidebar.

Opening the app reads saved snapshots immediately and starts one background source
refresh for the selected season. Manual **Refresh** remains available afterward;
there is no polling. SQLite keeps each source's latest validated snapshot and
refresh status. Failed updates preserve saved data and expose their errors.
Spread history lines load automatically once per displayed contract per page session.

Connected sources: nflverse schedules, team/player stats, play-by-play, depth charts
and FTN charting; Sharp's coverage table; official NFL injuries; and Kalshi spreads,
ten player-prop categories, public Kalshi game, team and player identities, and Elo game history (23 source datasets).
Source timestamps do not guarantee statistical freshness;
Sharp's statistical cutoff is unspecified and blank injury statuses mean unknown.

The Elo backend replays regular-season and playoff results from 2002 with margin
adjustment, franchise continuity, home advantage and offseason regression. Approved
settings are K=20, home advantage=50 and two-thirds retention toward 1500.
Refresh **Elo game history**, then read `/api/elo?season=2026` for ratings, current-season
logs and matchup expected scores. Outputs represent P(win) + half P(tie), not
spread-cover probabilities. Published scores after kickoff are the approved completion
convention; nflverse does not provide a separate final-status field. Home and matchup
cards show the API's ratings and expected scores; clicking a team opens its Elo
history. API handoff: [docs/elo-api.json](docs/elo-api.json).

All six team rankings now include supporting stats and clickable game logs, with
opponents' current ranks and the approved sack context. FTN-charted blitz rates
include per-game coverage. Missing values remain unavailable and incomplete results
are marked. Blitz-frequency rank #1 means most frequent, not most effective;
its rank opens the blitz game log. Exact ties share ranks and teams without usable charting
remain unranked. Calculations use current-season regular-season games (including overtime)
with published scores in the saved schedule. They update locally after source refreshes.
Each ranking metric also shows the league mean and median of equally weighted team
season values. Unavailable values are excluded and incomplete coverage is flagged.

**Defense by opponent position** adds five rankings: receiving yards allowed to
RB/FB, WR and TE, and rushing yards allowed to RB/FB and QB. Each uses yards allowed
per team game, with #1 allowing the fewest. Supporting stats show targets/receptions
or carries, yards per opportunity, touchdowns, and game coverage. These are totals
against position groups, not individual-player predictions; opponent strength is
not adjusted. Fullbacks are included in the explicitly labeled RB/FB group.

QB rushing uses official totals, including designed runs, scrambles and kneeldowns.
The three components appear separately where every QB's yards and carries reconcile
with play-by-play. Missing breakdowns do not erase verified official totals. Every
completed, verified game counts equally, including zeroes; missing/conflicting games
are flagged and excluded. Players use the position in each game's statistics.
Unidentified rows with all seven relevant fields explicitly zero are excluded with
a notice, and team totals must still reconcile. No minimum sample cutoff is applied.

These rankings appear in team research and relevant prop views alongside overall
defense ranks. Click a current-opponent or player-log rank to inspect its team log.
Combined rushing/receiving props show the two applicable position ranks separately.
League mean/median use each team's season value equally. Existing saved nflverse
snapshots supply all inputs; no new subscription or source is needed.

The weekly matchup view shows unstarted games, team logos, the default spread,
and alternate contracts. Opening a game shows both teams' rank comparisons,
clickable game logs, coverage tendencies, injury reports and depth charts.
Matching requires agreement on teams, season, week and kickoff. Contract team,
threshold and settlement wording are checked before showing prices. Games without
a verified contract remain visible; conflicts appear in matching notices.
Injury reports from a different season or week are marked unavailable.

Each matchup has a **Player props** view with passing/rushing/receiving yards,
receptions, passing touchdowns, passing attempts/completions, interceptions thrown,
rushing attempts, and combined rushing/receiving yards. Select a player/statistic
and threshold on a card, then open its current-season log. Cards show the saved
Yes ask; logs preserve the threshold, mark results that met it and expose the
original settlement rules. Logs include the opponent's
current relevant rank; combined yards show both passing- and rushing-defense ranks.
Missing records are not treated as zero or confirmed DNPs. Official player rushing
includes scrambles and kneeldowns.

Player matching requires one exact name-and-team match with an agreeing position;
logs then follow the NFL player ID across teams. Conflicts are reported and quotes
withheld. Other linked market types are listed as not yet supported; event links
do not guarantee open contracts. Broader prop support and visual verification
remain unfinished. The browser shortcut remains a development option; the current
distribution target is the desktop source launcher described above.

Spread charts are available on each weekly game card and in selected-spread details.
History loads automatically as cards or selected spreads appear. Use **Refresh lines**
for the displayed week's default spreads or **Refresh history** in matchup details to update or retry. Charts show hourly YES bid/ask closing midpoints on a fixed 0–100%
scale, with seven days selected initially and 24-hour/six-hour alternatives. Shorter
ranges reuse the same download. Hover or use the keyboard slider to inspect values;
selected-spread details also include an hourly quote table and source link.

Missing hours and invalid two-sided quotes break the line; trade prices never fill
those gaps. Newer markets may have less than seven days of history. Each chart shows
its fetch time, requested window and coverage. **Refresh history** fetches a new
window; failure leaves the previous chart visible with an error. History is kept
in memory across navigation, cleared on page reload, and never polls automatically.
Source-snapshot refreshes do not refresh charts. Weekly requests run sequentially.

The **Watchlist** saves specific spread and player-prop contracts across games and
seasons. Select a threshold, then **Watch** to save it and open the details popup.
The Watchlist tab uses the player-prop card styling: team logos and accents, a
player/team heading, threshold and ask price, saved side, and a short notes preview.
**Edit details** reopens the popup with **Your side**
(Yes / No / Not chosen) and **Notes** fields; use **Save** to persist them and close
the popup. Closing without saving keeps the draft for this session. The price
follows the selected side's ask, with Yes ask shown while undecided. Missing No asks
remain unavailable; they are never calculated from the Yes ask. Existing bookmarks
start with no chosen side and empty notes. Unsaved edits survive navigation within
the app, but require saving before a page reload or restart. **Record a bet** carries
the saved side and notes into the tracker, including when recording from the matching
spread or prop. Source refreshes cannot replace your notes; conflicting edits from
another tab require review. Bookmarks persist in SQLite across
restarts and source refreshes. Quotes come from the latest verified source snapshots,
not a stored price at the time of pinning. Unavailable contracts remain removable;
pregame quotes are withheld after kickoff. Watchlist records are separate from
tracker tickets and are not included in tracker JSON backups.

To record a combo, choose **Build combo**, select at least two watched picks, then
**Record combo**. Save each pick's side and any edited notes first. The tracker opens
a combo draft with all selected sides and market/game references, and each pick's
notes labeled by selection. Enter the actual total cost and payout, then save the
ticket. If a ticket form is already open, add the selected legs to it or start a new
combo. Existing notes are preserved; duplicate contracts and transfers exceeding
the ticket's leg or notes limit are rejected without dropping data.

Prop cards show a compact **Threshold / Yes ask** comparison table. Select a row to
change the active threshold. Player game logs add **Games hit** for every available
threshold, displayed as hits / verified games. Equality counts as a hit; missing
statistics are excluded, verified zeroes count, and logs without usable values show
unavailable. Counts use the existing current-season regular-season player logs.

The **Bet tracker** records singles and multi-leg combos placed elsewhere. It does
not submit orders. Set a default unit size, then use **Record a bet**, or start from
a spread/prop's **Record a bet** button. Enter the chosen side, actual total cost
including fees, and optionally the potential total payout. Unsupported research
markets can still be described and recorded manually.

Close a ticket only after the entire position is sold or settled, entering the
actual total received after fees, including the returned stake. A $9.99 cost with
a $10 unit size is 0.999u; a $20 return produces +$10.01 / +1.001u. Open stakes
are separate from realized results. Unit-size changes affect new tickets; saved
tickets retain their original size. Totals sum each ticket's units using that
original size, with exact arithmetic and visibly marked rounding for unit displays.
Tickets can be edited or reopened; individual partial sales are not tracked.

**Export / import backups** downloads all tickets and the default unit size as
JSON. Import validates the complete file, adds missing tickets and skips identical
ones. A conflicting ticket stops the import without changing saved records.
An existing default unit size is kept; an unset default is restored from the file.
Tickets persist across app restarts, source refreshes and season changes. Draft
forms survive navigation within the app but are not saved until **Save ticket**.

## Developer setup

Node.js with npm and Python with venv support are required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
```

## Legacy browser development runner

```bash
bash scripts/start.sh
```

This builds the interface when its source files change and starts one Python service at
<http://127.0.0.1:8000>. Keep the terminal running while using the app;
press Ctrl+C to stop it. The service listens only on this computer.
Repeating the command reuses an already-running healthy Deck service.
To apply code changes, stop the original service with Ctrl+C and start again.
An unrelated or unhealthy service on port 8000 produces a clear error; startup
does not stop other processes. Sources refresh once on opening. Use the header's
**Refresh** button or an individual source's **Refresh** button under **Data**
for another update. The visible season applies to nflverse datasets;
Kalshi game identities are also scoped to that season, using the cached spread events.
The other sources supply their currently published data. Season rollover rules remain
unresolved, so verify the season shown, especially around January and February.

## Install as an app

Open <http://127.0.0.1:8000> in Chrome or Edge, then open **Data** and select
**Install app** when the browser makes it available. Alternatively, use the
browser's address-bar install icon or menu install option. The installed shortcut
opens the Games page in its own window, with the same saved research and tracker.
Use this exact address consistently; `localhost` is a different browser origin.

Installation adds a browser app shortcut; it does not start the Python service.
Run `bash scripts/start.sh` and keep its terminal open before using the shortcut.
There is no login autostart or background daemon. After a successful first load,
the service worker provides a **Reconnect to Deck** recovery page if the service
is unreachable. The page includes local startup help. Start the service and select **Try again**. Only that recovery
page is cached by the worker: API responses, market quotes and tracker writes
are neither cached nor queued. Worker updates take effect after old app windows
and tabs are closed and the app is reopened. Vite development does not register it.

The manifest and icons follow the browser's
[PWA install requirements](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).
Installation availability and the prompt timing are controlled by the browser.
The production build, manifest/icon HTTP responses, recovery routing, startup
reuse/build skipping and simulated install-control flows have passed automated
checks. Actual browser installation, service-worker lifecycle behavior and visual
checks at phone, tablet and 27-inch desktop sizes are still pending because this
session has no connected browser. The visual pass should include prop menus near
screen edges, paired supporting-stat rows, modal scrolling/focus and reduced motion.

After this update, refresh all sources once to load the new Kalshi identities.
The new player identity and additional prop snapshots are needed for the player-props tab.
For individual refreshes, refresh **Spread contracts** before **Kalshi game identities**.
The game reader uses event-specific milestone lookups because the broad competition
query returned no games during verification. The team directory's "Retires / No Team"
placeholder is excluded with a source notice.

Local SQLite storage lives in `.data/kalshi-deck.sqlite3`. It stores compressed source
snapshots, provenance, and the latest refresh outcome, plus permanent tracker tickets
and settings in separate tables. This database now contains user-entered records;
keep tracker backups before moving or replacing it. Price history is fetched from
Kalshi on request. `.data/`, dependencies, and build outputs are ignored by Git.
The legacy local database filename is retained so existing data remains available.
Set `DECK_DATABASE_PATH` to use a different absolute persistent path; the directory
must be writable by the service account. `DECK_PUBLIC_ORIGIN` accepts one HTTPS
origin without a trailing slash and enforces it for API mutations. These settings
do not add user authentication. New tracker exports use the `deck-tracker` format
and continue to accept older `kalshi-deck-tracker` backups.

## Development

Build the interface once with `npm run build`, then start the backend:

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal, run `npm run dev`. Vite forwards `/api` requests to the
local Python service. Use the URL printed by Vite.

`npm run build` checks TypeScript and builds the interface. `/api/health`
checks that the backend can open its existing SQLite database.

Run calculation, source parsing, quote-selection and cache-failure checks with:

```bash
.venv/bin/python -m unittest discover -s tests -v
node --test tests/*.test.mjs
```

Source endpoints: `GET /api/sources?season=2026`,
`POST /api/sources/{name}/refresh?season=2026`, `GET /api/spreads`, and
`GET /api/markets/{series}/{ticker}/history?start=...&end=...&interval=60`.
History times are Unix seconds; intervals are 1, 60 or 1440 minutes.
History responses include raw candles, normalized closing-quote midpoint points,
the source URL, fetch time and requested window. Missing candles remain absent;
the chart displays missing hourly slots as gaps, never zeroes.
The spreads endpoint returns raw grouped contracts, not a kickoff-filtered game list.

`GET /api/matchups?season=2026&week=6` returns verified upcoming matchups,
spread choices, team research, source status and matching notices. Omit `week` to
select the earliest week with unstarted games in the saved schedule. Scheduled
kickoff uses America/New_York with daylight-saving conversion; market closing
times are never used as kickoff. The browser also removes games as kickoff passes
without polling external sources.

`GET /api/rankings?season=2026` calculates the six rankings, supporting stats,
blitz rates and team logs from saved snapshots only. It includes source timestamps,
refresh errors, per-metric coverage, and opponent current ranks. A missing source
does not become zero; independent available metrics can still be calculated.
Exact rational arithmetic preserves unrounded competition ties before serialization.
EPA classification uses nflverse pass/run indicators (including classified penalty
outcomes), with sacks/scrambles counted as dropbacks. See [instructions.md](instructions.md)
for the agreed exclusions, weighting, missing-data treatment, and supporting ratios.

`GET /api/position-defense?season=2026` calculates the five position-group defense
rankings, supporting stats, QB rushing breakdowns, team game logs, league mean/median,
coverage notices and source timestamps. It reads saved schedule, player/team stats
and play-by-play snapshots only. Player-prop and player-log endpoints also expose
the applicable current position ranks alongside existing overall defense ranks.

`GET /api/matchups/{game_id}/props?season=2026` returns verified player/statistic
groups and threshold contracts for an unstarted game, with matching issues,
unsupported linked series, and source status. `GET /api/players/{player_id}/games?season=2026&category=receiving_yards`
returns completed current-season player-game rows and current opponent ranks.
Both endpoints read saved snapshots only. The player ID is nflverse's GSIS ID;
category names match the prop source names in `/api/sources`.

Tracker endpoints: `GET /api/tracker`, `PUT /api/tracker/settings`,
`PUT /api/tracker/tickets/{uuid}`, `GET /api/tracker/export`, and
`POST /api/tracker/import`. Money crosses the API as decimal strings, never binary
floating-point numbers. Ticket saves carry a revision for conflict detection;
new tickets use a stable client-generated UUID and null revision, so retrying a
save cannot create a duplicate. Local JSON writes are required. The tracker has
no external API dependency. Validation evidence is in `docs/tracker-validation.json`.
