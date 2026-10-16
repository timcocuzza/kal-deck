from pathlib import Path
from contextlib import closing
import asyncio
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import app as api
from backend.storage import SnapshotStore
from backend.watchlist import WatchlistStore, WatchlistConflict


def entry(**changes):
    return {'ticker': 'KXNFLRECYDS-EXAMPLE-50', 'kind': 'prop', 'season': 2026, 'week': 6,
            'game_id': '2026_06_SEA_DEN', 'label': 'Player · Receiving yards · 50+', **changes}


def saved_entry(**changes):
    return {**entry(), 'side': '', 'notes': '', 'revision': 0, **changes}


def request(method, path, payload=None, origin=None):
    """Exercise the ASGI routes without an extra HTTP client dependency."""
    async def invoke():
        messages = []
        headers = [(b'host', b'127.0.0.1:8000'), (b'content-type', b'application/json')]
        if origin:
            headers.append((b'origin', origin.encode()))
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                 'query_string': b'', 'root_path': '', 'headers': headers,
                 'server': ('127.0.0.1', 8000), 'client': ('127.0.0.1', 50000)}
        async def receive():
            return {'type': 'http.request', 'body': json.dumps(payload).encode(), 'more_body': False}
        async def send(message):
            messages.append(message)
        await asyncio.wait_for(api.app(scope, receive, send), timeout=5)
        status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
        body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        return status, json.loads(body)
    return asyncio.run(invoke())


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'local.sqlite3'
        self.store = WatchlistStore(self.path)
        self.store.initialize()

    def test_cross_game_and_season_bookmarks_survive_restart_and_source_initialization(self):
        values = [entry(), entry(ticker='SPREAD-OTHER', kind='spread', game_id='2025_03_KC_BAL', season=2025, week=3)]
        for value in values:
            self.store.save(value)
        SnapshotStore(self.path).initialize()
        restarted = WatchlistStore(self.path)
        restarted.initialize()
        self.assertEqual(restarted.entries(), [saved_entry(**value) for value in values[::-1]])

    def test_retries_are_idempotent_and_thresholds_are_independent(self):
        self.store.save(entry())
        self.store.save(entry())
        self.store.save(entry(ticker='KXNFLRECYDS-EXAMPLE-60'))
        self.assertEqual(len(self.store.entries()), 2)
        self.store.remove(entry()['ticker'])
        self.store.remove(entry()['ticker'])
        self.assertEqual([e['ticker'] for e in self.store.entries()], ['KXNFLRECYDS-EXAMPLE-60'])

    def test_invalid_entries_do_not_write(self):
        for changes in [{'season': True}, {'week': 19}, {'kind': 'other'}, {'ticker': '../bad'}, {'label': ''},
                        {'label': 10}, {'game_id': '2025_06_SEA_DEN'}, {'week': 7}, {'yes_ask_dollars': '0.50'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.save(entry(**changes))
        self.assertEqual(self.store.entries(), [])

    def test_api_round_trip_and_invalid_cross_origin_writes(self):
        with patch.object(api, 'DATABASE', self.path):
            response = request('PUT', '/api/watchlist', entry())
            self.assertEqual(response, (200, {'entries': [saved_entry()]}))
            self.assertEqual(request('GET', '/api/watchlist'), response)
            self.assertEqual(request('PUT', '/api/watchlist', entry(week=2))[0], 422)
            self.assertEqual(request('PUT', '/api/watchlist', entry(), origin='https://example.com')[0], 403)
            self.assertEqual(request('DELETE', '/api/watchlist/' + entry()['ticker']), (200, {'entries': []}))

    def test_legacy_bookmarks_default_to_undecided_and_can_be_edited(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('INSERT INTO watchlist(ticker, entry) VALUES (?, ?)', (entry()['ticker'], json.dumps(entry())))
        self.assertEqual(self.store.entries(), [saved_entry()])
        notes = 'Lean No — usage dropped.\nCheck the injury report before kickoff.'
        self.store.update(entry()['ticker'], {'side': 'No', 'notes': notes, 'revision': 0})
        self.store.initialize()
        self.assertEqual(WatchlistStore(self.path).entries(), [saved_entry(side='No', notes=notes, revision=1)])

    def test_edit_retries_and_repinning_preserve_notes_and_do_not_duplicate(self):
        self.store.save(entry())
        self.store.save(entry(ticker='KXNFLRECYDS-EXAMPLE-60'))
        details = {'side': 'Yes', 'notes': 'Expect more targets.', 'revision': 0}
        self.store.update(entry()['ticker'], details)
        self.store.update(entry()['ticker'], details)
        self.store.save(entry())
        self.assertEqual(self.store.entries(), [saved_entry(ticker='KXNFLRECYDS-EXAMPLE-60'), saved_entry(**{**details, 'revision': 1})])
        self.store.update(entry()['ticker'], {'side': '', 'notes': '', 'revision': 1})
        self.assertEqual(self.store.entries()[1], saved_entry(revision=2))

    def test_stale_edit_and_removed_entry_cannot_overwrite_or_resurrect(self):
        self.store.save(entry())
        self.store.update(entry()['ticker'], {'side': 'No', 'notes': 'New notes', 'revision': 0})
        with self.assertRaises(WatchlistConflict):
            self.store.update(entry()['ticker'], {'side': 'Yes', 'notes': 'Stale notes', 'revision': 0})
        self.assertEqual(self.store.entries(), [saved_entry(side='No', notes='New notes', revision=1)])
        self.store.remove(entry()['ticker'])
        with self.assertRaises(LookupError):
            self.store.update(entry()['ticker'], {'side': 'Yes', 'notes': 'Stale notes', 'revision': 1})
        self.assertEqual(self.store.entries(), [])

    def test_invalid_details_leave_existing_notes_intact(self):
        self.store.save(entry())
        original = {'side': 'No', 'notes': 'Keep these notes', 'revision': 0}
        self.store.update(entry()['ticker'], original)
        for changes in [{'side': 'Over'}, {'side': None}, {'notes': None}, {'notes': 'x' * 10001},
                        {'revision': True}, {'revision': -1}, {'label': 'Changed identity'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.update(entry()['ticker'], {**original, 'revision': 1, **changes})
        self.assertEqual(self.store.entries(), [saved_entry(side='No', notes='Keep these notes', revision=1)])

    def test_patch_api_validates_conflicts_missing_entries_and_origin(self):
        path = '/api/watchlist/' + entry()['ticker']
        details = {'side': 'No', 'notes': 'Avoid an early buy.\nWait for news.', 'revision': 0}
        with patch.object(api, 'DATABASE', self.path):
            self.assertEqual(request('PATCH', path, details)[0], 404)
            self.store.save(entry())
            self.assertEqual(request('PATCH', path, details, origin='https://example.com')[0], 403)
            self.assertEqual(request('PATCH', path, {**details, 'side': 'Under'})[0], 422)
            expected = (200, {'entries': [saved_entry(**{**details, 'revision': 1})]})
            self.assertEqual(request('PATCH', path, details), expected)
            self.assertEqual(request('PATCH', path, details), expected)
            self.assertEqual(request('PATCH', path, {**details, 'notes': 'Stale overwrite'})[0], 409)
            self.assertEqual(request('GET', '/api/watchlist'), expected)
