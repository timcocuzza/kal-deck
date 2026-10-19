from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

from backend.catalog import RefreshService
from backend.sources.common import Resource, SourceData, SourceError
from backend.sources.kalshi import load_market
from backend.storage import SnapshotStore
from backend.watchlist import WatchlistStore
from backend.watchlist_tracking import WatchlistMonitor, sync_saved_quotes


TICKER = 'KXNFLRECYDS-EXAMPLE-50'
START = '2026-10-18T17:00:00+00:00'
BEFORE = '2026-10-18T16:00:00+00:00'


def market(**changes):
    return {'ticker': TICKER, 'market_type': 'binary', 'status': 'active', 'result': '',
            'yes_ask_dollars': '0.45', 'no_ask_dollars': '0.57', **changes}


class TrackingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'test.sqlite3'
        self.snapshots = SnapshotStore(self.path)
        self.snapshots.initialize()
        self.bookmarks = WatchlistStore(self.path)
        self.bookmarks.initialize()
        self.bookmarks.save({'ticker': TICKER, 'kind': 'prop', 'season': 2026, 'week': 6,
                             'game_id': '2026_06_SEA_DEN', 'label': 'Player · Receiving yards · 50+'})
        self.snapshots.save('schedule:2026', SourceData([{'game_id': '2026_06_SEA_DEN',
                            'season': 2026, 'week': 6, 'gameday': '2026-10-18', 'gametime': '13:00'}], '', BEFORE))

    def tracking(self):
        return self.bookmarks.entries()[0]['tracking']

    def observe(self, stamp=BEFORE, **changes):
        self.bookmarks.observe(TICKER, kickoff=START, market=market(**changes), fetched_at=stamp)

    def test_last_valid_asks_survive_missing_quotes_kickoff_and_restart(self):
        self.observe()
        self.observe('2026-10-18T16:59:00+00:00', yes_ask_dollars='0.51', no_ask_dollars=None)
        self.observe(START, yes_ask_dollars='0.99', no_ask_dollars='0.02')
        self.observe('2026-10-18T16:58:00+00:00', yes_ask_dollars='0.60', no_ask_dollars='NaN')
        self.bookmarks = WatchlistStore(self.path)
        self.bookmarks.initialize()
        self.assertEqual(self.tracking()['yes_ask'], {'dollars': '0.51', 'fetched_at': '2026-10-18T16:59:00+00:00'})
        self.assertEqual(self.tracking()['no_ask'], {'dollars': '0.57', 'fetched_at': BEFORE})

    def test_legacy_quote_is_captured_before_source_replacement(self):
        self.snapshots.save('receiving_yards', SourceData([market()], '', BEFORE))
        service = RefreshService(self.snapshots, lambda url: Resource(b'{"markets":[],"cursor":""}', url, START))
        service.refresh('receiving_yards', 2026)
        self.assertEqual(self.snapshots.read('receiving_yards').rows, [])
        self.assertEqual(self.tracking()['yes_ask']['dollars'], '0.45')
        sync_saved_quotes(self.path)
        self.assertEqual(self.tracking()['no_ask']['dollars'], '0.57')

    def test_spread_bookmarks_use_the_same_retention(self):
        self.bookmarks.remove(TICKER)
        ticker = 'KXNFLSPREAD-EXAMPLE-3'
        self.bookmarks.save({'ticker': ticker, 'kind': 'spread', 'season': 2026, 'week': 6,
                             'game_id': '2026_06_SEA_DEN', 'label': 'Seattle wins by over 3.5'})
        self.snapshots.save('spreads', SourceData([market(ticker=ticker)], '', BEFORE))
        sync_saved_quotes(self.path)
        self.assertEqual(self.tracking()['yes_ask']['dollars'], '0.45')

    def test_observations_preserve_user_edits_and_do_not_resurrect_removed_entries(self):
        self.bookmarks.update(TICKER, {'side': 'No', 'notes': 'Keep me', 'revision': 0})
        self.observe()
        self.bookmarks.update(TICKER, {'side': 'Yes', 'notes': 'Edited', 'revision': 1})
        self.observe(START, status='finalized', result='no')
        entry = self.bookmarks.entries()[0]
        self.assertEqual((entry['side'], entry['notes'], entry['revision']), ('Yes', 'Edited', 2))
        self.assertEqual(entry['tracking']['result'], 'no')
        self.bookmarks.remove(TICKER)
        self.observe()
        self.assertEqual(self.bookmarks.entries(), [])

    def test_missing_or_invalid_quotes_and_unresolved_results_stay_unknown(self):
        for value in (None, 'NaN', 'Infinity', '0', '1', '-0.2', 'bad'):
            self.observe(yes_ask_dollars=value, no_ask_dollars=value, status='closed')
        self.assertNotIn('yes_ask', self.tracking())
        self.assertNotIn('no_ask', self.tracking())
        self.assertNotIn('result', self.tracking())
        self.observe(START, status='finalized', result='scalar')
        self.assertEqual(self.tracking()['result'], 'scalar')

    def test_unknown_kickoff_never_saves_a_potential_in_game_ask(self):
        self.bookmarks.observe(TICKER, market=market(), fetched_at=BEFORE)
        self.assertNotIn('yes_ask', self.tracking())

    def test_corrected_kickoff_discards_later_quotes(self):
        self.observe()
        self.bookmarks.observe(TICKER, kickoff='2026-10-18T15:59:00+00:00')
        self.assertNotIn('yes_ask', self.tracking())

    def test_monitor_fetches_near_kickoff_then_results_and_keeps_asks_on_failure(self):
        self.observe()
        calls = []
        stamp = '2026-10-18T16:59:00+00:00'
        result = market(yes_ask_dollars='0.52')
        def load(ticker):
            calls.append(ticker)
            if result is None:
                raise SourceError('Offline')
            return SourceData([result], '', stamp)
        monitor = WatchlistMonitor(self.path, load)
        monitor.refresh(datetime.fromisoformat(BEFORE))
        self.assertEqual(calls, [])
        monitor.refresh(datetime.fromisoformat(stamp))
        self.assertEqual(len(calls), 1)
        monitor.refresh(datetime.fromisoformat(stamp))
        self.assertEqual(len(calls), 1)
        result = None
        monitor.refresh(datetime(2026, 10, 18, 20, tzinfo=timezone.utc))
        self.assertEqual(self.tracking()['error'], 'Offline')
        self.assertEqual(self.tracking()['yes_ask']['dollars'], '0.52')
        stamp = '2026-10-18T20:05:00+00:00'
        result = market(status='finalized', result='yes', yes_ask_dollars='0.99')
        monitor.refresh(datetime.fromisoformat(stamp))
        self.assertIsNone(self.tracking()['error'])
        self.assertEqual(self.tracking()['result'], 'yes')
        self.assertEqual(self.tracking()['yes_ask']['dollars'], '0.52')
        count = len(calls)
        monitor.refresh(datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.assertEqual(len(calls), count)

    def test_fetch_that_finishes_after_kickoff_does_not_save_live_quote(self):
        self.observe()
        monitor = WatchlistMonitor(self.path, lambda ticker: SourceData([market(yes_ask_dollars='0.90')], '', START))
        monitor.refresh(datetime(2026, 10, 18, 16, 59, 59, tzinfo=timezone.utc))
        self.assertEqual(self.tracking()['yes_ask']['dollars'], '0.45')


class MarketLookupTests(unittest.TestCase):
    def test_archived_fallback_and_contract_validation(self):
        urls = []
        def fetch(url):
            urls.append(url)
            if '/historical/' not in url:
                raise SourceError('Source returned HTTP 404.')
            return Resource(json.dumps({'market': market(status='finalized', result='no')}).encode(), url, START)
        self.assertEqual(load_market(TICKER, fetch).rows[0]['result'], 'no')
        self.assertEqual(len(urls), 2)
        for payload in ({}, {'market': market(ticker='OTHER')}, {'market': market(market_type='scalar')}):
            with self.assertRaises(SourceError):
                load_market(TICKER, lambda url: Resource(json.dumps(payload).encode(), url, START))

    def test_transient_failures_do_not_retry_the_archive(self):
        calls = []
        def fetch(url):
            calls.append(url)
            raise SourceError('Source returned HTTP 429.')
        with self.assertRaises(SourceError):
            load_market(TICKER, fetch)
        self.assertEqual(len(calls), 1)
