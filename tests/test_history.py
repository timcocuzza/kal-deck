import json
import unittest

from backend.sources.common import Resource, SourceError
from backend.sources.kalshi import history_points, load_history


TICKER = 'KXNFLSPREAD-TEST-TEAM3'


def candle(timestamp, bid='0.48', ask='0.51', trade=None):
    return {'end_period_ts': timestamp, 'yes_bid': {'close_dollars': bid},
            'yes_ask': {'close_dollars': ask}, 'price': {'close_dollars': trade}}


def load(rows, **overrides):
    response = {'ticker': TICKER, 'candlesticks': rows, **overrides}
    return load_history('KXNFLSPREAD', TICKER, 0, 14400, 60,
                        lambda url: Resource(json.dumps(response).encode(), url, '2026-10-15T00:00:00Z'))


class HistoryTests(unittest.TestCase):
    def test_midpoint_uses_closing_quotes_even_without_trades(self):
        result = history_points([candle(3600), candle(7200, trade='0.90')])
        self.assertEqual([point['midpoint'] for point in result], [0.495, 0.495])
        self.assertEqual(result[0]['bid'], '0.48')
        self.assertEqual(result[0]['ask'], '0.51')

    def test_missing_invalid_or_one_sided_quotes_never_use_trade_prices(self):
        rows = [candle(3600, bid=bid, ask=ask, trade='0.50') for bid, ask in [
            (None, '0.51'), ('0.48', None), ('0', '0.51'), ('0.48', '1'),
            ('0.60', '0.50'), ('NaN', '0.51'), ('0.48', 'Infinity'), ('bad', '0.51'),
        ]]
        rows.extend([{'end_period_ts': 3600, 'yes_bid': None, 'yes_ask': []},
                     {'end_period_ts': 3600, 'price': {'close_dollars': '0.50'}}])
        self.assertTrue(all(point['midpoint'] is None for point in history_points(rows)))

    def test_sorting_does_not_fill_missing_periods(self):
        rows = [candle(10800), candle(3600)]
        result = history_points(load(rows).rows)
        self.assertEqual([point['timestamp'] for point in result], [3600, 10800])
        self.assertEqual(len(result), 2)

    def test_duplicate_and_out_of_window_timestamps_rejected(self):
        for rows in ([candle(3600), candle(3600)], [candle(-1)], [candle(14401)]):
            with self.subTest(rows=rows), self.assertRaises(SourceError):
                load(rows)

    def test_invalid_timestamp_and_wrong_contract_rejected(self):
        for timestamp in (True, None, '3600', 3600.5):
            with self.subTest(timestamp=timestamp), self.assertRaises(SourceError):
                load([candle(timestamp)])
        with self.assertRaises(SourceError):
            load([], ticker='KXNFLSPREAD-OTHER-TEAM3')

    def test_empty_history_is_valid_and_no_synthetic_candle_requested(self):
        result = load([])
        self.assertEqual(history_points(result.rows), [])
        self.assertNotIn('include_latest_before_start=true', result.url)


if __name__ == '__main__':
    unittest.main()
