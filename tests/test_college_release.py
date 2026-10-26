"""Cross-sport persistence, postseason identity and rate-limit regressions."""
from copy import deepcopy
from datetime import datetime, timezone
from email.message import Message
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from backend import app as api
from backend.catalog import RefreshService
from backend.college import college_matchups, college_rankings
from backend.college_markets import attach_college_markets
from backend.sources.college_markets import load_college_markets
from backend.sources.college_market_fetch import CollegeMarketFetch
from backend.sources.college_schedule import load_current_schedule, parse_week
from backend.sources.common import Resource, SourceData, RateLimitError, SourceError, fetch_public
from backend.storage import SnapshotStore
from backend.watchlist import WatchlistStore
from backend.watchlist_tracking import sync_saved_quotes, WatchlistMonitor
from test_college_markets import baseline, current, espn, market_bundle, NOW, EVENT
from test_watchlist import request, entry as nfl_entry


def bookmark(**changes):
    return {'sport': 'cfb', 'season_type': 'postseason', 'ticker': EVENT + '-BYU8', 'kind': 'spread',
            'season': 2026, 'week': 1, 'game_id': '123', 'label': 'BYU vs UCF · BYU −7.5', **changes}


class StoreFixture:
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'db'
        self.store = SnapshotStore(self.path); self.store.initialize()
        self.watches = WatchlistStore(self.path); self.watches.initialize()


class StoredTests(StoreFixture, unittest.TestCase):
    def test_college_and_legacy_nfl_bookmarks_round_trip_and_keep_notes(self):
        with patch.object(api, 'DATABASE', self.path):
            self.assertEqual(request('PUT', '/api/watchlist', nfl_entry())[0], 200)
            self.assertEqual(request('PUT', '/api/watchlist', bookmark())[0], 200)
            status, result = request('PATCH', '/api/watchlist/' + bookmark()['ticker'],
                                     {'side': 'No', 'notes': 'Schedule strength', 'revision': 0})
            self.assertEqual(status, 200)
        saved = WatchlistStore(self.path).entries()
        self.assertEqual(len(saved), 2)
        self.assertEqual((saved[0]['sport'], saved[0]['season_type'], saved[0]['side'], saved[0]['notes']),
                         ('cfb', 'postseason', 'No', 'Schedule strength'))
        self.assertNotIn('sport', saved[1])
        for changes in ({'kind': 'prop'}, {'game_id': '2026_01_BYU_UCF'}, {'week': 31},
                        {'season_type': 'spring'}, {'ticker': 'KXNFLSPREAD-TEST'}, {'sport': 'nba'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.watches.save(bookmark(**changes))

    def test_college_tracker_ticket_persists_and_exports_with_legacy_nfl_leg(self):
        from uuid import uuid4
        from backend.tracker import TrackerStore
        from test_tracker import ticket
        tracker = TrackerStore(self.path); tracker.initialize()
        pick = bookmark()
        college = {'description': pick['label'], 'selection': 'No',
                   'market_ticker': pick['ticker'], 'game_id': pick['game_id']}
        data = ticket(kind='combo', notes='College schedule strength')
        data['legs'].append(college)
        tracker.save(str(uuid4()), data)
        exported = TrackerStore(self.path).export()['tickets'][0]
        self.assertEqual(exported['legs'], data['legs'])
        self.assertEqual(exported['notes'], data['notes'])

    def seed(self):
        rows = current(); rows[0].update(season_type='postseason', week='1')
        self.store.save('cfb_schedule:2026', SourceData(rows, '', NOW.isoformat()))
        markets = market_bundle(); markets['markets'][0]['no_ask_dollars'] = '.54'
        self.store.save('cfb_markets:2026', SourceData([markets], '', NOW.isoformat()))
        self.watches.save(bookmark())

    def test_college_pregame_quotes_survive_replacement_and_official_settlement(self):
        self.seed(); sync_saved_quotes(self.path)
        self.assertEqual(self.watches.entries()[0]['tracking']['yes_ask']['dollars'], '0.48')
        self.store.save('cfb_markets:2026', SourceData([{'markets': []}], '', NOW.isoformat()))
        final = {**market_bundle()['markets'][0], 'status': 'finalized', 'result': 'no'}
        monitor = WatchlistMonitor(self.path, lambda ticker: SourceData([final], '', '2026-10-25T00:00Z'))
        monitor.refresh(datetime(2026, 10, 25, tzinfo=timezone.utc))
        tracked = self.watches.entries()[0]['tracking']
        self.assertEqual(tracked['result'], 'no')
        self.assertEqual(tracked['yes_ask']['dollars'], '0.48')
        self.assertEqual(tracked['no_ask']['dollars'], '0.54')

    def test_wrong_phase_and_tbd_do_not_capture_pregame_quotes(self):
        self.seed()
        self.watches.remove(bookmark()['ticker'])
        self.watches.save(bookmark(season_type='regular'))
        sync_saved_quotes(self.path)
        self.assertNotIn('yes_ask', self.watches.entries()[0].get('tracking', {}))
        rows = current(); rows[0].update(week='1', start_time_tbd='true')
        self.store.save('cfb_schedule:2026', SourceData(rows, '', NOW.isoformat()))
        sync_saved_quotes(self.path)
        self.assertNotIn('yes_ask', self.watches.entries()[0].get('tracking', {}))

    def test_cfb_refresh_captures_previous_quotes_before_replacing_snapshot(self):
        self.seed()
        with patch('backend.catalog.SourceSpec.load', return_value=SourceData([{'markets': []}], '', NOW.isoformat())):
            self.assertEqual(RefreshService(self.store).refresh('cfb_markets', 2026)['status'], 'ready')
        self.assertEqual(self.watches.entries()[0]['tracking']['yes_ask']['dollars'], '0.48')


class PostseasonTests(unittest.TestCase):
    def test_unassigned_bowls_stay_visible_without_stats_or_market_matches(self):
        data = espn(); data['season']['type'] = 3; data['week']['number'] = 1
        event = data['events'][0]; event['season']['type'] = 3; event['week']['number'] = 1
        for i, team in enumerate(event['competitions'][0]['competitors']):
            tid = str(112350 + i)
            team.update(id=tid, team={'id': tid, 'displayName': 'TBA', 'location': 'TBA', 'abbreviation': 'TBA'})
        rows = parse_week(data, 2026, 1, {}, {}, season_type=3)
        result = college_matchups({'schedule': rows}, 2026, season_type='postseason', now=NOW)
        attach_college_markets(result, rows, market_bundle(), 2026)
        self.assertEqual(len(result['games']), 1)
        self.assertFalse(result['games'][0]['participants_confirmed'])
        self.assertIsNone(result['games'][0]['home']['logo'])
        self.assertEqual(result['games'][0]['markets'], [])
        resolved = espn(); resolved['season']['type'] = 3; resolved['week']['number'] = 1
        resolved['events'][0]['season']['type'] = 3; resolved['events'][0]['week']['number'] = 1
        updated = parse_week(resolved, 2026, 1, {'123': rows[0]}, {'2116': 'fbs', '252': 'fbs'}, season_type=3)
        self.assertTrue(updated[0]['participants_confirmed'])

    def test_regular_and_postseason_week_one_never_mix_and_next_phase_is_automatic(self):
        regular = {**current()[0], 'week': '1'}
        bowl = {**regular, 'game_id': '456', 'season_type': 'postseason', 'start_date': '2027-01-01T18:00Z'}
        bundle = {'schedule': [regular, bowl]}
        result = college_matchups(bundle, 2026, week=1, now=NOW)
        self.assertEqual([g['game_id'] for g in result['games']], ['123'])
        result = college_matchups(bundle, 2026, week=1, season_type='postseason', now=NOW)
        self.assertEqual([g['game_id'] for g in result['games']], ['456'])
        self.assertEqual(len(result['periods']), 2)
        result = college_matchups(bundle, 2026, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(result['season_type'], 'postseason')
        self.assertEqual(result['games'][0]['game_id'], '456')

    def test_postseason_rounds_without_division_or_week_match_exact_game(self):
        rows = current(); rows[0].update(season_type='postseason', week='1')
        bundle = market_bundle(); details = bundle['milestones'][0]['details']
        details['season'] = {'year': 2026, 'type': 'PST', 'round': 2}; details.pop('division')
        def fetch(url):
            path = urlsplit(url).path
            payload = {'markets': bundle['markets']} if path.endswith('/markets') else {'structured_targets': bundle['targets']} if path.endswith('/structured_targets') else {'milestones': bundle['milestones']}
            return Resource(json.dumps(payload).encode(), url, NOW.isoformat())
        loaded = load_college_markets(2026, fetch)
        result = college_matchups({'schedule': rows}, 2026, season_type='postseason', now=NOW)
        attach_college_markets(result, rows, loaded.rows[0], 2026)
        self.assertEqual(result['games'][0]['default_market_ticker'], EVENT + '-BYU8')
        for changes in ({'type': 'REG', 'week': 1}, {'year': 2025}):
            bad = deepcopy(bundle); bad['milestones'][0]['details']['season'].update(changes)
            attach_college_markets(result, rows, bad, 2026)
            self.assertEqual(result['games'][0]['markets'], [])
        bad = deepcopy(bundle); bad['milestones'][0]['start_date'] = 'invalid'
        attach_college_markets(result, rows, bad, 2026)
        self.assertEqual(result['games'][0]['markets'], [])

    def test_schedule_queries_bowls_and_rejects_omitted_known_postseason_games(self):
        bowl = {**baseline(), 'game_id': '456', 'week': '1', 'season_type': 'postseason'}
        def fetch(url):
            query = parse_qs(urlsplit(url).query); phase = int(query['seasontype'][0]); week = int(query['week'][0])
            data = espn()
            if (phase, week) not in ((2, 8), (3, 1)):
                data = {'events': []}
            elif phase == 3:
                data['season']['type'] = 3; data['week']['number'] = 1
                event = data['events'][0]; event['season']['type'] = 3; event['week']['number'] = 1
                event['id'] = event['competitions'][0]['id'] = '456'
            return Resource(json.dumps(data).encode(), url, NOW.isoformat())
        result = load_current_schedule(2026, [baseline(), bowl], fetch)
        self.assertEqual({r['season_type'] for r in result.rows}, {'regular', 'postseason'})
        def missing(url):
            return Resource(b'{"events":[]}', url, NOW.isoformat()) if 'seasontype=3' in url else fetch(url)
        with self.assertRaisesRegex(SourceError, 'omitted'):
            load_current_schedule(2026, [baseline(), bowl], missing)

    def test_completed_bowls_count_in_facets_without_fcs_public_statistics(self):
        from test_college import bundle
        data = bundle()
        for row in data['schedule']:
            row['season_type'] = 'postseason'
        ranks = college_rankings(data, 2026, now=NOW)
        self.assertGreater(ranks['teams']['1']['categories']['passing_offense']['games_used'], 0)
        self.assertNotIn('9', ranks['teams'])  # fixture's FCS opponent


class MarketFetchTests(StoreFixture, unittest.TestCase):
    def make_fetch(self, callback):
        self.now = NOW.timestamp(); self.waits = []
        def sleep(seconds):
            self.waits.append(seconds); self.now += seconds
        return CollegeMarketFetch(callback, self.store, clock=lambda: self.now, sleep=sleep)

    def test_cache_survives_reader_restart_and_different_resources_expire_separately(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return Resource(b'{"cursor":""}', url, datetime.fromtimestamp(self.now, timezone.utc).isoformat())
        reader = self.make_fetch(fetch)
        urls = ['https://test/markets?page=1', 'https://test/milestones?event=a', 'https://test/structured_targets']
        for url in urls: reader(url)
        reader = CollegeMarketFetch(fetch, self.store, clock=lambda: self.now, sleep=lambda seconds: None)
        for url in urls: reader(url)
        self.assertEqual(len(calls), 3)
        self.now += 16
        for url in urls: reader(url)
        self.assertEqual(len(calls), 4)
        self.now += 301
        for url in urls: reader(url)
        self.assertEqual(len(calls), 6)
        self.assertTrue(any(wait >= .34 for wait in self.waits))

    def test_rate_limits_retry_bounded_then_persist_cooldown(self):
        calls = []
        def limited(url):
            calls.append(url); raise RateLimitError()
        reader = self.make_fetch(limited)
        with self.assertRaises(RateLimitError): reader('https://test/markets')
        self.assertEqual(len(calls), 3)
        self.assertIn(1, self.waits); self.assertIn(2, self.waits)
        restarted = CollegeMarketFetch(limited, self.store, clock=lambda: self.now)
        with self.assertRaisesRegex(SourceError, 'cooling down'): restarted('https://test/markets')
        self.assertEqual(len(calls), 3)
        self.now += 31
        with self.assertRaises(RateLimitError): reader('https://test/markets')
        self.assertEqual(len(calls), 6)

    def test_short_retry_after_recovers_and_long_retry_after_does_not_block(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if len(calls) == 1: raise RateLimitError(3)
            return Resource(b'{}', url, datetime.fromtimestamp(self.now, timezone.utc).isoformat())
        reader = self.make_fetch(fetch); reader('https://test/markets')
        self.assertIn(3, self.waits); self.assertEqual(len(calls), 2)
        def limited(url): raise RateLimitError(120)
        reader = self.make_fetch(limited)
        with self.assertRaises(RateLimitError): reader('https://test/milestones')
        self.assertEqual(self.waits, [])
        self.assertEqual(self.store.read('cfb_http:cooldown').rows[0]['until'], self.now + 120)

    def test_rate_limit_preserves_last_good_report(self):
        saved = SourceData([market_bundle()], 'test', NOW.isoformat())
        self.store.save('cfb_markets:2026', saved)
        def fetch(url): raise RateLimitError(90)
        status = RefreshService(self.store, fetch).refresh('cfb_markets', 2026)
        self.assertEqual(status['status'], 'refresh_failed')
        self.assertEqual(self.store.read('cfb_markets:2026').rows, saved.rows)

    def test_http_retry_after_seconds_and_date_are_preserved(self):
        for value in ('12', 'Mon, 26 Oct 2099 17:00:00 GMT', 'invalid'):
            headers = Message(); headers['Retry-After'] = value
            error = HTTPError('https://test', 429, 'limit', headers, None)
            with patch('backend.sources.common.urlopen', side_effect=error):
                with self.assertRaises(RateLimitError) as result: fetch_public('https://test')
            error.close()
            if value == '12': self.assertEqual(result.exception.retry_after, 12)
            elif value == 'invalid': self.assertIsNone(result.exception.retry_after)
            else: self.assertGreater(result.exception.retry_after, 0)
