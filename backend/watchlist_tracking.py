"""Retain pregame quotes and check official outcomes while Deck is running."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .matchups import kickoff
from .props import SERIES_TYPES
from .sources.common import SourceError
from .sources.kalshi import load_market
from .storage import SnapshotStore
from .watchlist import WatchlistStore, timestamp


def sync_saved_quotes(path):
    bookmarks = WatchlistStore(path)
    entries = bookmarks.entries()
    snapshots = SnapshotStore(path)
    cache = {}

    def read(key):
        if key not in cache:
            cache[key] = snapshots.read(key)
        return cache[key]

    for entry in entries:
        college = entry.get('sport', 'nfl') == 'cfb'
        schedule = read(f"{'cfb_schedule' if college else 'schedule'}:{entry['season']}")
        games = [game for game in schedule.rows if game.get('game_id') == entry['game_id']
                 and str(game.get('season')) == str(entry['season'])
                 and str(game.get('week')) == str(entry['week'])
                 and (not college or game.get('season_type') == entry.get('season_type', 'regular'))] if schedule else []
        start = None
        if len(games) == 1:
            game = games[0]
            if college:
                if game.get('schedule_verified') and game.get('start_time_tbd') == 'false' and game.get('status') != 'STATUS_POSTPONED':
                    start = timestamp(game.get('start_date'))
            else:
                start = kickoff(game)
        source = 'spreads' if entry['kind'] == 'spread' else SERIES_TYPES.get(entry['ticker'].split('-')[0])
        snapshot = read(f"cfb_markets:{entry['season']}" if college else source) if source else None
        rows = snapshot.rows[0].get('markets', []) if college and snapshot and snapshot.rows else snapshot.rows if snapshot else []
        markets = [row for row in rows if row.get('ticker') == entry['ticker']]
        if start or len(markets) == 1:
            bookmarks.observe(entry['ticker'], kickoff=start.isoformat() if start else None,
                              market=markets[0] if len(markets) == 1 else None,
                              fetched_at=snapshot.fetched_at if snapshot else None)


class WatchlistMonitor:
    def __init__(self, path, load=load_market):
        self.path = path
        self.load = load

    def refresh(self, now=None):
        now = now or datetime.now(timezone.utc)
        sync_saved_quotes(self.path)
        bookmarks = WatchlistStore(self.path)
        due = []
        for entry in bookmarks.entries():
            tracking = entry.get('tracking', {})
            if tracking.get('market_status') in ('finalized', 'settled'):
                continue
            start = timestamp(tracking.get('kickoff'))
            remaining = (start - now).total_seconds() if start else None
            near_kickoff = remaining is not None and 0 < remaining <= 300
            missing_quote = not tracking.get('yes_ask') or not tracking.get('no_ask')
            if remaining is not None and remaining > 300 and not missing_quote:
                continue
            checked = timestamp(tracking.get('checked_at'))
            interval = 30 if near_kickoff else 300
            if checked and (now - checked).total_seconds() < interval:
                continue
            due.append(entry)

        def refresh_entry(entry):
            try:
                data = self.load(entry['ticker'])
                bookmarks.observe(entry['ticker'], market=data.rows[0], fetched_at=data.fetched_at,
                                  checked_at=now.isoformat())
            except SourceError as error:
                bookmarks.observe(entry['ticker'], checked_at=now.isoformat(), error=str(error))

        # Pregame requests go first; a slow archived contract must not block all quotes.
        def priority(entry):
            start = timestamp(entry.get('tracking', {}).get('kickoff')) or now
            return (not 0 < (start - now).total_seconds() <= 300, start)

        due.sort(key=priority)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(refresh_entry, due))
