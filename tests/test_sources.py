import csv
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest

from backend.catalog import RefreshService
from backend.sources.common import Resource, SourceData, SourceError
from backend.sources.kalshi import load_history, load_markets, quote_midpoint, select_default_spread
from backend.sources.nflverse import load_dataset
from backend.sources.pages import load_coverage, load_injuries
from backend.storage import SnapshotStore


STAMP = "2026-10-15T00:00:00+00:00"


def fetch_body(body):
    if isinstance(body, str):
        body = body.encode()
    return lambda url: Resource(body, url, STAMP)


def csv_body(headers, rows, compressed=False):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    body = buffer.getvalue().encode()
    return gzip.compress(body) if compressed else body


def market(ticker="A", bid="0.49", ask="0.51", volume="100"):
    return {"ticker": f"KXNFLSPREAD-GAME-{ticker}", "event_ticker": "KXNFLSPREAD-GAME",
            "market_type": "binary", "yes_bid_dollars": bid, "yes_ask_dollars": ask,
            "volume_fp": volume}


class MarketTests(unittest.TestCase):
    def test_midpoint_then_gap_then_volume(self):
        farther = market("F", "0.50", "0.52", "99999")
        wide = market("W", "0.48", "0.52", "99999")
        narrow = market("N", "0.49", "0.51", "10")
        liquid = market("L", "0.49", "0.51", "20")
        self.assertEqual(select_default_spread([farther, wide, narrow, liquid]), liquid)

    def test_opposite_side_equal_distance_uses_gap(self):
        below = market("B", "0.47", "0.51")
        above = market("A", "0.50", "0.52")
        self.assertEqual(select_default_spread([below, above]), above)

    def test_missing_crossed_or_nonfinite_quotes_never_default(self):
        invalid = [market(bid=x, ask=y) for x, y in [
            (None, "0.5"), ("0", "0.5"), ("0.5", "1"),
            ("0.6", "0.4"), ("NaN", "0.5"), ("0.5", "Infinity"),
        ]]
        for item in invalid:
            self.assertIsNone(quote_midpoint(item))
        self.assertIsNone(select_default_spread(invalid))
        self.assertEqual(len(invalid), 6)

    def test_pagination_and_duplicate_records(self):
        responses = iter([{"markets": [market()], "cursor": "next"},
                          {"markets": [market(), market("B")], "cursor": ""}])
        urls = []
        def fetch(url):
            urls.append(url)
            return Resource(json.dumps(next(responses)).encode(), url, STAMP)
        self.assertEqual(len(load_markets("KXNFLSPREAD", fetch).rows), 2)
        self.assertIn("cursor=next", urls[1])

    def test_repeating_cursor_and_malformed_pages_fail(self):
        for response in [{"markets": [], "cursor": "same"}, {"markets": None},
                         {"markets": [{}]}, {"markets": [], "cursor": None}]:
            with self.assertRaises(SourceError):
                load_markets("KXNFLSPREAD", fetch_body(json.dumps(response)))

    def test_history_keeps_missing_trade_and_time_gap(self):
        ticker = market()["ticker"]
        rows = [{"end_period_ts": 60, "price": {"close": None}},
                {"end_period_ts": 180, "price": {"close": "0.51"}}]
        response = {"ticker": ticker, "candlesticks": rows}
        result = load_history("KXNFLSPREAD", ticker, 0, 240, 1, fetch_body(json.dumps(response)))
        self.assertEqual(result.rows, rows)


class TableTests(unittest.TestCase):
    def test_coverage_keeps_published_rates_and_publication_date(self):
        table = '<script type="application/ld+json">{"@type":"NewsArticle","dateModified":"2026-10-13"}</script>'
        table += '<table><tr><th>Team</th><th>Man Rate</th><th>Zone Rate</th></tr>'
        table += ''.join(f'<tr><td>Team {i}</td><td>20%</td><td>70%</td></tr>' for i in range(32))
        table += '</table>'
        result = load_coverage(fetch_body(table))
        self.assertEqual(result.rows[0]["zone_percentage"], 70)
        self.assertEqual(result.source_updated_at, "2026-10-13")
        with self.assertRaises(SourceError):
            load_coverage(fetch_body(table.replace('Team 31', 'Team 30')))
        with self.assertRaises(SourceError):
            load_coverage(fetch_body(table[:-8]))

    def test_injury_blanks_are_unknown_and_team_is_preserved(self):
        html = '''<h1>2026 NFL Injury Report</h1><h2>Injuries - WEEK 6</h2>
        <div class="d3-o-section-sub-title"><div>Seahawks</div></div>
        <table><tr><th>Player</th><th>Position</th><th>Injuries</th>
        <th>Practice Status</th><th>Game Status</th></tr>
        <tr><td><a>Test Player</a></td><td>WR</td><td>Knee</td><td>Limited</td><td></td></tr></table>'''
        result = load_injuries(fetch_body(html))
        self.assertIsNone(result.rows[0]["game_status"])
        self.assertEqual(result.rows[0]["team_name"], "Seahawks")
        self.assertEqual(result.context["week"], 6)
        with self.assertRaises(SourceError):
            load_injuries(fetch_body('<h1>2026 NFL Injury Report</h1>Injuries - WEEK 6'))

    def test_depth_uses_latest_snapshot_separately_for_each_team(self):
        headers = ['dt', 'team', 'player_name', 'gsis_id', 'espn_id', 'pos_abb', 'pos_rank']
        rows = [['2026-10-01', 'SEA', 'Old', '', '', 'WR', '1'],
                ['2026-10-03', 'SEA', 'New', '', '', 'WR', '1'],
                ['2026-10-02', 'DEN', 'Other', '', '', 'WR', '1']]
        result = load_dataset('depth_charts', 2026, fetch_body(csv_body(headers, rows, True)))
        self.assertEqual({r['player_name'] for r in result.rows}, {'New', 'Other'})

    def test_schedule_filters_season_and_rejects_missing_columns(self):
        headers = ['season', 'week', 'game_id', 'game_type', 'gameday', 'gametime', 'home_team', 'away_team', 'home_score', 'away_score']
        rows = [[year, 1, str(year), 'REG', '2026-09-10', '20:00', 'SEA', 'DEN', '', ''] for year in [2025, 2026]]
        result = load_dataset('schedule', 2026, fetch_body(csv_body(headers, rows)))
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]['season'], '2026')
        with self.assertRaises(SourceError):
            load_dataset('schedule', 2026, fetch_body('season,week\n2026,6'))
        with self.assertRaises(SourceError):
            load_dataset('schedule', 2027, fetch_body(csv_body(headers, rows)))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / 'cache.sqlite3')
        self.store.initialize()

    def test_failure_keeps_previous_data_and_fetch_time_then_recovers(self):
        old = SourceData([market()], 'https://example.test', STAMP)
        self.store.save('spreads', old)
        service = RefreshService(self.store, fetch_body('{"markets":null}'))
        status = service.refresh('spreads', 2026)
        self.assertEqual(status['status'], 'refresh_failed')
        self.assertEqual(status['fetched_at'], STAMP)
        self.assertEqual(self.store.read('spreads').rows, old.rows)
        service.fetch = fetch_body('{"markets":[],"cursor":""}')
        status = service.refresh('spreads', 2026)
        self.assertEqual(status['status'], 'ready')
        self.assertIsNone(status['error'])
        self.assertEqual(self.store.read('spreads').rows, [])

    def test_initial_failure_is_unavailable(self):
        def offline(url):
            raise SourceError('Offline')
        service = RefreshService(self.store, offline)
        status = service.refresh('spreads', 2026)
        self.assertEqual(status['error'], 'Offline')
        self.assertIsNone(status['fetched_at'])
        self.assertIsNone(self.store.read('spreads'))

    def test_overlapping_refresh_is_rejected(self):
        service = RefreshService(self.store)
        with service.locks['spreads'], self.assertRaises(SourceError):
            service.refresh('spreads', 2026)


if __name__ == '__main__':
    unittest.main()
