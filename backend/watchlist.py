"""Permanent contract bookmarks, separate from replaceable source snapshots."""

from contextlib import closing
import json
import re
import sqlite3


class WatchlistConflict(Exception):
    pass


def with_details(entry):
    return {'side': '', 'notes': '', 'revision': 0, **entry}


def validate_entry(entry):
    if set(entry) != {'ticker', 'kind', 'season', 'week', 'game_id', 'label'}:
        raise ValueError('Supply a contract, game, season, week, kind and label.')
    if entry['kind'] not in ('prop', 'spread'):
        raise ValueError('Unknown watchlist kind.')
    for field, low, high in [('season', 1999, 2100), ('week', 1, 18)]:
        if type(entry[field]) is not int or not low <= entry[field] <= high:
            raise ValueError(f'Invalid {field}.')
    for field, limit in [('ticker', 200), ('game_id', 100), ('label', 300)]:
        value = entry[field]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'Invalid {field}.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', entry['ticker']):
        raise ValueError('Invalid contract ticker.')
    if not entry['game_id'].startswith(f"{entry['season']}_{entry['week']:02d}_"):
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
