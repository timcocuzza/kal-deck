"""Serve the local browser app and manually refreshed research sources."""

from contextlib import asynccontextmanager, closing
from pathlib import Path
import asyncio
import logging
import json
import os
import sqlite3
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .catalog import BY_NAME, SOURCES, CFB_SOURCES, RefreshService
from .college import college_matchups, college_rankings, reconcile_college_schedule
from .college_markets import attach_college_markets
from .college_strength import calculate_strength
from .sources.common import SourceError
from .sources.kalshi import load_history, history_points, quote_midpoint, select_default_spread
from .storage import SnapshotStore
from .rankings import CATEGORIES, calculate_rankings
from .matchups import build_matchups, research_for_team
from .props import PROP_TYPES, build_props, build_player_log
from .position_defense import calculate_position_defense, position_rank_context
from .tracker import TrackerStore, TrackerError, TrackerConflict
from .elo import calculate_elo
from .watchlist import WatchlistStore, WatchlistConflict
from .watchlist_tracking import WatchlistMonitor, sync_saved_quotes
from .security import DesktopAccess, PrivateAPIResponses, allowed_origins, validate_write_origin


ROOT = Path(__file__).resolve().parent.parent
# Keep the legacy local filename so existing records are not silently abandoned.
DATABASE = Path(os.environ.get("DECK_DATABASE_PATH", ROOT / ".data" / "kalshi-deck.sqlite3")).expanduser().resolve()
DIST = ROOT / "dist"
store = SnapshotStore(DATABASE)
refresh_service = RefreshService(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    allowed_origins()  # Reject malformed hosted configuration before accepting traffic.
    if not (DIST / "index.html").is_file():
        raise RuntimeError("Browser build missing. Run npm run build first.")
    store.initialize()
    TrackerStore(DATABASE).initialize()
    WatchlistStore(DATABASE).initialize()
    stop = asyncio.Event()
    monitor = WatchlistMonitor(DATABASE)

    async def watch_contracts():
        while not stop.is_set():
            try:
                await asyncio.to_thread(monitor.refresh)
            except Exception:
                logging.exception('Watchlist update failed; saved quotes and results remain available.')
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(watch_contracts())
    try:
        yield
    finally:
        stop.set()
        await task


desktop_mode = bool(os.environ.get('DECK_DESKTOP_TOKEN'))
app = FastAPI(title="Deck", lifespan=lifespan, dependencies=[Depends(validate_write_origin)],
              docs_url=None if desktop_mode else '/docs',
              redoc_url=None if desktop_mode else '/redoc',
              openapi_url=None if desktop_mode else '/openapi.json')
app.add_middleware(PrivateAPIResponses)
app.add_middleware(DesktopAccess)


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        with closing(sqlite3.connect(f"{DATABASE.as_uri()}?mode=rw", uri=True)) as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail="Local storage unavailable") from error
    return {"status": "ok", "database": "ok"}


@app.get("/api/sources")
def sources(season: int = Query(ge=1999, le=2100), sport: Literal['nfl', 'cfb'] = 'nfl'):
    return {"sources": [refresh_service.status(source.name, season) for source in (CFB_SOURCES if sport == 'cfb' else SOURCES)]}


def college_report(season, operation, **kwargs):
    snapshot = store.read(BY_NAME['cfb_research'].key(season))
    source = refresh_service.status('cfb_research', season)
    if snapshot is None:
        return {'available': False, 'season': season, 'sources': [source],
                'warnings': ['College data has not been downloaded for this season.']}
    try:
        current = store.read(BY_NAME['cfb_schedule'].key(season))
        bundle, warnings = reconcile_college_schedule(snapshot.rows[0], current.rows if current else [])
        result = operation(bundle, season, **kwargs)
        result['warnings'].extend(warnings)
        if operation is college_matchups:
            markets = store.read(BY_NAME['cfb_markets'].key(season))
            attach_college_markets(result, bundle['schedule'], markets.rows[0] if markets else {}, season)
    except SourceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    names = ['cfb_schedule'] + (['cfb_markets'] if operation is college_matchups else [])
    statuses = [source] + [refresh_service.status(name, season) for name in names]
    if current is None:
        result['warnings'].append('Current college schedule is unavailable; bulk kickoff times cannot verify spreads.')
    return {**result, 'available': True, 'sources': statuses}


@app.get('/api/cfb/matchups')
def cfb_matchups(season: int = Query(ge=1999, le=2100), week: int | None = Query(default=None, ge=0, le=30),
                 season_type: Literal['regular', 'postseason'] | None = None):
    return college_report(season, college_matchups, week=week, season_type=season_type)


@app.get('/api/cfb/rankings')
def cfb_rankings(season: int = Query(ge=1999, le=2100), include_fcs: bool = False,
                 game_id: str | None = Query(default=None, pattern=r'^\d{1,12}$')):
    return college_report(season, college_rankings, include_fcs=include_fcs, game_id=game_id)


@app.post("/api/sources/{name}/refresh")
def refresh_source(name: str, season: int = Query(ge=1999, le=2100)):
    if name not in BY_NAME:
        raise HTTPException(status_code=404, detail="Unknown data source")
    try:
        return refresh_service.refresh(name, season)
    except SourceError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get('/api/cfb/strength')
def cfb_strength(season: int = Query(ge=2014, le=2100)):
    snapshot = store.read(f'cfb_strength:{season}')
    source = refresh_service.status('cfb_strength', season)
    if snapshot is None:
        return {'available': False, 'season': season, 'sources': [source],
                'warnings': ['Refresh college strength history to load ratings.']}
    try:
        result = calculate_strength(snapshot.rows[0], season)
    except (SourceError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail='Saved college strength history needs review.') from error
    result['sources'] = [source]
    return result


@app.get("/api/spreads")
def spreads():
    snapshot = store.read("spreads")
    if snapshot is None:
        return {"events": [], "source": store.status("spreads")}
    grouped: dict[str, list[dict]] = {}
    for market in snapshot.rows:
        grouped.setdefault(market["event_ticker"], []).append(market)
    events = []
    for ticker, markets in grouped.items():
        default = select_default_spread(markets)
        events.append({
            "event_ticker": ticker,
            "default_market_ticker": default["ticker"] if default else None,
            "markets": [{**market, "midpoint": float(midpoint) if midpoint is not None else None}
                        for market in markets for midpoint in [quote_midpoint(market)]],
        })
    return {"events": events, "source": store.status("spreads")}


@app.get("/api/markets/{series}/{ticker}/history")
def history(series: str, ticker: str, start: int = Query(ge=0), end: int = Query(ge=0),
            interval: int = Query()):
    try:
        data = load_history(series, ticker, start, end, interval)
    except SourceError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"candlesticks": data.rows, "points": history_points(data.rows),
            "fetched_at": data.fetched_at, "context": data.context, "url": data.url}


@app.get("/api/rankings")
def rankings(season: int = Query(ge=1999, le=2100)):
    names = ("schedule", "team_stats", "play_by_play", "ftn_charting")
    snapshots = {name: store.read(BY_NAME[name].key(season)) for name in names}
    try:
        result = calculate_rankings(season, *[
            snapshots[name].rows if snapshots[name] is not None else [] for name in names
        ])
    except SourceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    result["sources"] = [refresh_service.status(name, season) for name in names]
    for name, snapshot in snapshots.items():
        if snapshot is None:
            result["warnings"].append(f"{BY_NAME[name].label} has not been downloaded for {season}.")
    return result


@app.get('/api/elo')
def elo(season: int = Query(ge=2002, le=2100)):
    snapshot = store.read(BY_NAME['elo_history'].key(season))
    source = refresh_service.status('elo_history', season)
    if snapshot is None:
        return {'season': season, 'available': False, 'teams': [], 'matchups': [],
                'sources': [source], 'warnings': [f'Elo game history has not been downloaded for {season}.']}
    try:
        result = calculate_elo(season, snapshot.rows)
    except SourceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {**result, 'available': True, 'sources': [source]}


@app.get("/api/matchups")
def matchups(season: int = Query(ge=1999, le=2100), week: int | None = Query(default=None, ge=1, le=18)):
    names = ("schedule", "spreads", "kalshi_games", "kalshi_teams", "coverage", "injuries", "depth_charts")
    snapshots = {name: store.read(BY_NAME[name].key(season)) for name in names}
    result = build_matchups(season, *[
        snapshots[name].rows if snapshots[name] else []
        for name in ("schedule", "spreads", "kalshi_games", "kalshi_teams")
    ], week=week)
    for game in result["games"]:
        for side in ("away", "home"):
            game[side]["research"] = research_for_team(
                game[side]["code"], season, result["week"],
                snapshots["coverage"], snapshots["injuries"], snapshots["depth_charts"],
            )
    result["sources"] = [refresh_service.status(name, season) for name in names]
    result["warnings"] = [f"{BY_NAME[name].label} has not been downloaded."
                          for name, snapshot in snapshots.items() if snapshot is None]
    return result


@app.get('/api/position-defense')
def position_defense(season: int = Query(ge=1999, le=2100)):
    names = ('schedule', 'player_stats', 'team_stats', 'play_by_play')
    snapshots = {name: store.read(BY_NAME[name].key(season)) for name in names}
    try:
        result = calculate_position_defense(season, *[
            snapshots[name].rows if snapshots[name] is not None else [] for name in names
        ])
    except SourceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    result['sources'] = [refresh_service.status(name, season) for name in names]
    result['warnings'].extend(f'{BY_NAME[name].label} has not been downloaded.'
                              for name, snapshot in snapshots.items() if snapshot is None)
    return result


def context_rankings(season, position=False):
    try:
        return position_defense(season) if position else rankings(season)
    except HTTPException as error:
        return {'teams': [], 'sources': [], 'warnings': [f'Opponent rankings unavailable: {error.detail}']}


@app.get("/api/matchups/{game_id}/props")
def player_props(game_id: str, season: int = Query(ge=1999, le=2100)):
    names = ("schedule", "kalshi_games", "kalshi_teams", "kalshi_players", "player_stats", "depth_charts", *PROP_TYPES)
    snapshots = {name: store.read(BY_NAME[name].key(season)) for name in names}
    def rows(name):
        return snapshots[name].rows if snapshots[name] is not None else []
    result = build_props(season, game_id, rows('schedule'),
                         [market for name in PROP_TYPES for market in rows(name)],
                         rows('kalshi_games'), rows('kalshi_teams'), rows('kalshi_players'),
                         rows('player_stats'), rows('depth_charts'))
    result['sources'] = [refresh_service.status(name, season) for name in names]
    result['categories'] = [{'key': key, 'label': spec[1]} for key, spec in PROP_TYPES.items()]
    result['warnings'].extend(f'{BY_NAME[name].label} has not been downloaded.'
                              for name, snapshot in snapshots.items() if snapshot is None)
    if result['groups']:
        overall, positional = context_rankings(season), context_rankings(season, position=True)
        indexed = {team['team']: team for team in overall['teams']}
        for group in result['groups']:
            opponent = indexed.get(group['opponent'], {})
            group['opponent_ranks'] = []
            for key in PROP_TYPES[group['category']][4]:
                headline = opponent.get('categories', {}).get(key, {}).get('headline', {})
                group['opponent_ranks'].append({'category': key, 'label': CATEGORIES[key][0],
                                               'rank': headline.get('rank'), 'incomplete': headline.get('incomplete', True)})
            group['opponent_ranks'].extend(position_rank_context(positional['teams'], group['opponent'], group['category'], group['player']['position']))
        sources_by_name = {s['name']: s for s in result['sources'] + overall['sources'] + positional['sources']}
        result['sources'] = list(sources_by_name.values())
        result['warnings'].extend(dict.fromkeys(overall['warnings'] + positional['warnings']))
    return result


@app.get("/api/players/{player_id}/games")
def player_games(player_id: str, season: int = Query(ge=1999, le=2100), category: str = Query()):
    if category not in PROP_TYPES:
        raise HTTPException(status_code=422, detail='Unsupported player statistic')
    names = ('schedule', 'player_stats')
    snapshots = {name: store.read(BY_NAME[name].key(season)) for name in names}
    ranks = context_rankings(season)
    positional = context_rankings(season, position=True)
    result = build_player_log(season, player_id, category,
                              *[snapshots[name].rows if snapshots[name] else [] for name in names], ranks['teams'], positional['teams'])
    sources_by_name = {source['name']: source for source in ranks['sources'] + positional['sources']}
    sources_by_name.update({name: refresh_service.status(name, season) for name in names})
    result['sources'] = list(sources_by_name.values())
    result['warnings'].extend(ranks['warnings'])
    result['warnings'].extend(positional['warnings'])
    result['warnings'].extend(f'{BY_NAME[name].label} has not been downloaded.'
                              for name, snapshot in snapshots.items() if snapshot is None)
    return result


def tracker_write_request(request: Request):
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(status_code=415, detail='Requests require JSON.')


def tracker_call(operation, *args):
    try:
        return getattr(TrackerStore(DATABASE), operation)(*args)
    except TrackerConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except TrackerError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail='Tracker storage is unavailable. Keep your entries and try again.') from error


@app.get('/api/tracker')
def tracker_report():
    return tracker_call('report')


@app.put('/api/tracker/settings', dependencies=[Depends(tracker_write_request)])
def tracker_settings(payload: dict):
    if set(payload) != {'default_unit_size'}:
        raise HTTPException(status_code=422, detail='Supply only the default unit size.')
    return tracker_call('set_unit', payload['default_unit_size'])


@app.put('/api/tracker/tickets/{ticket_id}', dependencies=[Depends(tracker_write_request)])
def tracker_save(ticket_id: str, payload: dict):
    if set(payload) != {'ticket', 'revision'}:
        raise HTTPException(status_code=422, detail='Supply a ticket and its revision (null for a new ticket).')
    return tracker_call('save', ticket_id, payload['ticket'], payload['revision'])


@app.get('/api/tracker/export')
def tracker_export():
    backup = tracker_call('export')
    return Response(json.dumps(backup, indent=2, ensure_ascii=False), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="deck-tracker.json"',
                             'Cache-Control': 'no-store'})


@app.post('/api/tracker/import', dependencies=[Depends(tracker_write_request)])
def tracker_import(payload: dict):
    if len(json.dumps(payload).encode()) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Tracker backups must be at most 10 MB.')
    return tracker_call('import_backup', payload)


def watchlist_call(operation, *args):
    try:
        bookmarks = WatchlistStore(DATABASE)
        if operation != 'entries':
            getattr(bookmarks, operation)(*args)
        sync_saved_quotes(DATABASE)
        return {'entries': bookmarks.entries()}
    except WatchlistConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail='Watchlist storage unavailable. Try again.') from error


@app.get('/api/watchlist')
def watchlist_report():
    return watchlist_call('entries')


@app.put('/api/watchlist', dependencies=[Depends(tracker_write_request)])
def watchlist_save(payload: dict):
    return watchlist_call('save', payload)


@app.delete('/api/watchlist/{ticker}', dependencies=[Depends(tracker_write_request)])
def watchlist_remove(ticker: str):
    return watchlist_call('remove', ticker)


@app.patch('/api/watchlist/{ticker}', dependencies=[Depends(tracker_write_request)])
def watchlist_update(ticker: str, payload: dict):
    return watchlist_call('update', ticker, payload)


# Register API routes before mounting the built browser assets.
app.mount("/", StaticFiles(directory=DIST, html=True, check_dir=False), name="browser")
