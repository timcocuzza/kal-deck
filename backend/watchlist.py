"""Permanent contract bookmarks, separate from replaceable source snapshots."""

from contextlib import closing
import json
import re
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def ask(value):
    try:
        number = Decimal(str(value))
        return str(number) if number.is_finite() and 0 < number < 1 else None
    except InvalidOperation:
        return None


class WatchlistConflict(Exception):
    pass


def with_details(entry):
    return {'side': '', 'notes': '', 'revision': 0, **entry}


def validate_entry(entry):
    required = {'ticker', 'kind', 'season', 'week', 'game_id', 'label'}
    if not required <= set(entry) or set(entry) - required - {'sport', 'season_type'}:
        raise ValueError('Supply a contract, game, season, week, kind and label.')
    sport = entry.get('sport', 'nfl')
    phase = entry.get('season_type', 'regular')
    if sport not in ('nfl', 'cfb') or phase not in ('regular', 'postseason') or (sport == 'nfl' and phase != 'regular'):
        raise ValueError('Invalid sport or season phase.')
    if entry['kind'] not in ('prop', 'spread'):
        raise ValueError('Unknown watchlist kind.')
    for field, low, high in [('season', 1999, 2100), ('week', 0 if sport == 'cfb' else 1, 30 if sport == 'cfb' else 18)]:
        if type(entry[field]) is not int or not low <= entry[field] <= high:
            raise ValueError(f'Invalid {field}.')
    for field, limit in [('ticker', 200), ('game_id', 100), ('label', 300)]:
        value = entry[field]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'Invalid {field}.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', entry['ticker']):
        raise ValueError('Invalid contract ticker.')
    if sport == 'cfb':
        if (entry['kind'] != 'spread' or not re.fullmatch(r'[0-9]+', entry['game_id'])
                or not entry['ticker'].startswith('KXNCAAFSPREAD-')):
            raise ValueError('Supply a college spread and ESPN game ID.')
    elif not entry['game_id'].startswith(f"{entry['season']}_{entry['week']:02d}_"):
        raise ValueError('Game must agree with the season and week.')
    return entry


class WatchlistStore:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT PRIMARY KEY, entry TEXT NOT NULL)')

    def entries(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return [with_details(json.loads(row[0])) for row in connection.execute('SELECT entry FROM watchlist ORDER BY rowid DESC')]

    def save(self, entry):
        validate_entry(entry)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('INSERT INTO watchlist(ticker, entry) VALUES (?, ?) ON CONFLICT(ticker) DO NOTHING',
                               (entry['ticker'], json.dumps(with_details(entry))))

    def update(self, ticker, details):
        if set(details) != {'side', 'notes', 'revision'}:
            raise ValueError('Supply side, notes and revision.')
        if details['side'] not in ('', 'Yes', 'No'):
            raise ValueError('Choose Yes, No or no side yet.')
        if not isinstance(details['notes'], str) or len(details['notes']) > 10000:
            raise ValueError('Notes must be text up to 10,000 characters.')
        if type(details['revision']) is not int or details['revision'] < 0:
            raise ValueError('Invalid watchlist revision.')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT entry FROM watchlist WHERE ticker=?', (ticker,)).fetchone()
            if row is None:
                raise LookupError('This watchlist entry was removed. Reload the watchlist.')
            entry = with_details(json.loads(row[0]))
            if all(entry[key] == details[key] for key in ('side', 'notes')):
                return
            if entry['revision'] != details['revision']:
                raise WatchlistConflict('This watchlist entry changed elsewhere. Reload the watchlist and review your draft before saving.')
            entry.update(side=details['side'], notes=details['notes'], revision=entry['revision'] + 1)
            connection.execute('UPDATE watchlist SET entry=? WHERE ticker=?', (json.dumps(entry), ticker))

    def remove(self, ticker):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('DELETE FROM watchlist WHERE ticker=?', (ticker,))

    def observe(self, ticker, *, kickoff=None, market=None, fetched_at=None, checked_at=None, error=None):
        """Merge source observations without changing user revisions or reviving deletions."""
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT entry FROM watchlist WHERE ticker=?', (ticker,)).fetchone()
            if row is None:
                return
            entry = json.loads(row[0])
            tracking = entry.setdefault('tracking', {})
            if timestamp(kickoff):
                tracking['kickoff'] = kickoff
                # A corrected schedule must not turn an in-game quote into a pregame one.
                for side in ('yes', 'no'):
                    quote = tracking.get(side + '_ask')
                    if quote and timestamp(quote['fetched_at']) >= timestamp(kickoff):
                        tracking.pop(side + '_ask')
            fetched, start = timestamp(fetched_at), timestamp(tracking.get('kickoff'))
            if market and market.get('ticker') == ticker and market.get('market_type') == 'binary' and fetched:
                if start and fetched < start and market.get('status') in ('active', 'open') and not market.get('result'):
                    for side in ('yes', 'no'):
                        value = ask(market.get(side + '_ask_dollars'))
                        previous = tracking.get(side + '_ask')
                        if value is not None and (not previous or fetched > timestamp(previous['fetched_at'])):
                            tracking[side + '_ask'] = {'dollars': value, 'fetched_at': fetched_at}
                previous_result = timestamp(tracking.get('result_fetched_at'))
                if (market.get('status') in ('determined', 'finalized', 'settled')
                        and market.get('result') in ('yes', 'no', 'scalar', 'void')
                        and (previous_result is None or fetched >= previous_result)):
                    tracking.update(result=market['result'], market_status=market['status'], result_fetched_at=fetched_at)
            if checked_at:
                tracking.update(checked_at=checked_at, error=error)
            connection.execute('UPDATE watchlist SET entry=? WHERE ticker=?', (json.dumps(entry), ticker))
