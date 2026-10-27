from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from backend.elo import APPROVED_CONFIG, replay_elo
from backend.margins import PointsFit, rolling_nfl, attach_nfl_margins, attach_college_margins
from scripts.backtest_margins import market_backtest
from test_college_strength import result, bundle
from test_elo_integration import season_rows

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
SOURCES = [{'name': n, 'fetched_at': NOW.isoformat(), 'error': None} for n in ('schedule', 'strength')]


def cfb_fixture():
    history = bundle(result(), {**result('2', day='11-01'), 'completed': 'false', 'status': 'STATUS_SCHEDULED'})
    game = dict(game_id='2', season_type='regular', week=1, kickoff='2026-11-01T18:00:00+00:00', neutral=False,
                schedule_verified=True, participants_confirmed=True, time_tbd=False, status='STATUS_SCHEDULED',
                home={'id': '1', 'is_fbs': True}, away={'id': '2', 'is_fbs': True})
    return {'season': 2026, 'games': [game]}, history


def nfl_fixture():
    rows = [r for y in range(2002, 2027) for r in season_rows(y)]
    future = {**season_rows(2026, unscored=True)[0], 'game_id': 'next', 'gameday': '2026-11-01', 'week': '2'}
    rows.append(future)
    game = dict(game_id='next', kickoff='2026-11-01T18:00:00+00:00', neutral=False, venue_verified=True, week=2,
                home={'code': future['home_team']}, away={'code': future['away_team']})
    return {'season': 2026, 'games': [game]}, rows


class MarginsTests(unittest.TestCase):
    def test_saved_sources_age_across_boundary_on_repeated_api_builds(self):
        for attach, fixture in ((attach_nfl_margins, nfl_fixture), (attach_college_margins, cfb_fixture)):
            report, data = fixture()
            boundary = NOW + timedelta(hours=24)
            attach(report, data, SOURCES, now=boundary)
            before = deepcopy(report['games'][0]['margin_forecast'])
            self.assertTrue(before['available'], before)
            self.assertEqual(before['freshness_policy']['max_source_age_hours'], 24)
            attach(report, data, SOURCES, now=boundary + timedelta(milliseconds=1))
            after = report['games'][0]['margin_forecast']
            self.assertFalse(after['available'])
            self.assertIsNone(after['home_margin'])
            self.assertIn('older than 24 hours', after['unavailable_reason'])
            self.assertEqual(before['training_cutoff'], after['training_cutoff'])
            self.assertEqual(before['source_freshness'][0]['fetched_at'], after['source_freshness'][0]['fetched_at'])
            self.assertNotEqual(before['prediction_as_of'], after['prediction_as_of'])

    def test_fit_learns_points_from_results_not_probabilities(self):
        fit = PointsFit()
        for i in range(256):
            x = (i % 20 - 10) * 10
            fit.add(dict(season=2007, home_rating_before=1500+x, away_rating_before=1500, home_advantage=0,
                         home_score=100+x*.05, away_score=100, neutral=True, kickoff='2007-09-01T00:00:00+00:00'))
        self.assertAlmostEqual(fit.coefficient, .05)
        self.assertEqual(fit.n, 256)

    def test_nfl_date_freeze_and_historical_corrections(self):
        games = [dict(game_id=str(i), season=2007, kickoff=(datetime(2007, 9, 1, 18, tzinfo=timezone.utc)+timedelta(days=3*(i//16))).isoformat(),
                      home_team=f'H{i%16}', away_team=f'A{i%16}', neutral=False, home_score=20, away_score=10) for i in range(304)]
        def forecasts(rows):
            return rolling_nfl(replay_elo(rows, APPROVED_CONFIG, freeze_dates=True)['games'])[0]
        first = forecasts(games)
        changed = deepcopy(games); changed[256]['home_score'] = 70
        second = forecasts(changed)
        self.assertEqual([r['home_margin'] for r in first[:272]], [r['home_margin'] for r in second[:272]])
        self.assertNotEqual(first[272]['home_margin'], second[272]['home_margin'])
        for row in first[272:]:
            self.assertLess(row['training_cutoff'][:10], row['prediction_as_of'][:10])
        reverse = [g for i in range(0, len(games), 16) for g in reversed(games[i:i+16])]
        self.assertEqual({r['game_id']: r['home_margin'] for r in first}, {r['game_id']: r['home_margin'] for r in forecasts(reverse)})

    def test_nfl_upcoming_neutral_and_exact_join(self):
        report, rows = nfl_fixture()
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        f = report['games'][0]['margin_forecast']
        self.assertTrue(f['available'], f)
        home = f['home_margin']; beta = f['calibration']['points_per_elo']
        rows[-1]['location'] = 'Neutral'; report['games'][0]['neutral'] = True
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        self.assertAlmostEqual(home-report['games'][0]['margin_forecast']['home_margin'], 50*beta)
        report['games'][0]['kickoff'] = '2026-11-01T19:00:00+00:00'
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        self.assertIn('context', report['games'][0]['margin_forecast']['unavailable_reason'])

    def test_missing_stale_unknown_and_refresh_failure(self):
        for attach, fixture in ((attach_nfl_margins, nfl_fixture), (attach_college_margins, cfb_fixture)):
            report, data = fixture()
            attach(report, None, SOURCES, now=NOW)
            self.assertIn('not been downloaded', report['games'][0]['margin_forecast']['unavailable_reason'])
            for fetched, text in (((NOW-timedelta(days=2)).isoformat(), 'older than'), (None, 'unknown')):
                attach(report, data, [{'name': 'test', 'fetched_at': fetched}], now=NOW)
                f = report['games'][0]['margin_forecast']
                self.assertIsNone(f['home_margin']); self.assertIn(text, f['unavailable_reason'])
            attach(report, data, [{**SOURCES[0], 'error': 'offline'}], now=NOW)
            self.assertTrue(report['games'][0]['margin_forecast']['available'])
            self.assertIn('refresh failed', report['games'][0]['margin_forecast']['notices'][0])

    def test_college_neutral_early_season_and_fcs(self):
        report, data = cfb_fixture()
        attach_college_margins(report, data, SOURCES, now=NOW)
        f = report['games'][0]['margin_forecast']
        self.assertTrue(f['available'], f)
        self.assertAlmostEqual(f['home_margin'], 12.4)
        self.assertTrue(f['experimental']); self.assertIn('Early season', ' '.join(f['notices']))
        report['games'][0]['neutral'] = data['games'][-1]['neutral'] = True
        attach_college_margins(report, data, SOURCES, now=NOW)
        self.assertAlmostEqual(report['games'][0]['margin_forecast']['home_margin'], 10.4)
        report['games'][0]['away']['is_fbs'] = False
        attach_college_margins(report, data, SOURCES, now=NOW)
        self.assertIn('FCS', report['games'][0]['margin_forecast']['unavailable_reason'])
        self.assertIsNone(report['games'][0]['margin_forecast']['home_margin'])

    def test_college_context_and_completed_fail_closed(self):
        for update in ({'season': 2025}, {'neutral': True}, {'home': '3'}, {'phase': 'postseason'}, {'week': 2}, {'completed': True}):
            report, data = cfb_fixture(); data['games'][-1].update(update)
            attach_college_margins(report, data, SOURCES, now=NOW)
            self.assertFalse(report['games'][0]['margin_forecast']['available'], update)
        for update in ({'participants_confirmed': False}, {'time_tbd': True}, {'schedule_verified': False}, {'kickoff': '2026-10-26T18:00:00Z'}):
            report, data = cfb_fixture(); report['games'][0].update(update)
            attach_college_margins(report, data, SOURCES, now=NOW)
            self.assertFalse(report['games'][0]['margin_forecast']['available'], update)

    def test_college_same_date_results_do_not_enter_live_forecast(self):
        report, data = cfb_fixture()
        data['games'][0].update(kickoff='2026-10-27T01:00:00+00:00', day='2026-10-27')
        attach_college_margins(report, data, SOURCES, now=NOW)
        self.assertEqual(report['games'][0]['margin_forecast']['home_margin'], 2)
        data['games'][0]['home_score'] = 100
        attach_college_margins(report, data, SOURCES, now=NOW)
        self.assertEqual(report['games'][0]['margin_forecast']['home_margin'], 2)

    def test_pending_prior_game_blocks_forecast(self):
        report, data = cfb_fixture()
        data['games'][0].update(completed=False, status='STATUS_IN_PROGRESS')
        attach_college_margins(report, data, SOURCES, now=NOW)
        self.assertIn('awaiting', report['games'][0]['margin_forecast']['unavailable_reason'])
        report, rows = nfl_fixture()
        rows.append({**rows[-1], 'game_id': 'pending', 'gameday': '2026-10-01'})
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        self.assertIn('awaiting', report['games'][0]['margin_forecast']['unavailable_reason'])

    def test_nfl_completed_started_unknown_venue_and_corrected_score(self):
        report, rows = nfl_fixture()
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        original = report['games'][0]['margin_forecast']['home_margin']
        rows[0]['home_score'] = '70'
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        self.assertNotEqual(original, report['games'][0]['margin_forecast']['home_margin'])
        game = report['games'][0]
        game['venue_verified'] = False
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        self.assertFalse(game['margin_forecast']['available'])
        game['venue_verified'] = True
        game['kickoff'] = '2026-10-25T17:00:00+00:00'
        rows[-1].update(gameday='2026-10-25', home_score='14', away_score='7')
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        self.assertIn('started', game['margin_forecast']['unavailable_reason'])

    def test_nfl_live_embargo_withholds_recent_result(self):
        report, rows = nfl_fixture()
        rows[-1]['game_id'] = 'next'
        # A result within the preceding 24h is unavailable at the daily origin.
        rows[-17]['gameday'] = '2026-10-26'
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        first = report['games'][0]['margin_forecast']['home_margin']
        rows[-17]['home_score'] = '70'
        attach_nfl_margins(report, rows, SOURCES, now=NOW)
        self.assertEqual(first, report['games'][0]['margin_forecast']['home_margin'])

    def test_market_zero_weight_and_zero_correction_are_allowed(self):
        rows, lines = [], []
        for i in range(257):
            year = 2018 if i < 256 else 2025
            game = dict(sport='nfl', game_id=str(i), season=year, home='A', away='B',
                        kickoff=f'{year}-09-02T18:00:00Z', prediction_as_of=f'{year}-09-02T00:00:00Z',
                        strength=10, actual=3)
            rows.append(game)
            lines.append(dict(sport='nfl', game_id=str(i), season=str(year), home_id='A', away_id='B',
                              kickoff=game['kickoff'], quoted_at=f'{year}-09-01T18:00:00Z',
                              observed_at=f'{year}-09-01T19:00:00Z', source='fixture',
                              line_convention='home_expected_margin', home_line='3'))
        audit = market_backtest(rows, lines)['sports']['nfl']
        self.assertEqual(audit['strength_weight'], 0)
        self.assertEqual(audit['residual_correction'], 0)
        self.assertEqual(audit['development_metrics']['market']['mae'], 0)
        # Evaluation outcomes cannot influence the chosen weight/correction.
        rows[-1]['actual'] = 100
        other = market_backtest(rows, lines)['sports']['nfl']
        self.assertEqual(other['strength_weight'], 0)
        self.assertEqual(other['residual_correction'], 0)

    def test_market_sign_time_and_identity_rejections(self):
        game = dict(sport='nfl', game_id='1', season=2025, home='A', away='B', kickoff='2025-09-02T18:00:00Z',
                    prediction_as_of='2025-09-02T00:00:00Z', strength=3, actual=7)
        line = dict(sport='nfl', game_id='1', season='2025', home_id='A', away_id='B', kickoff=game['kickoff'],
                    quoted_at='2025-09-01T20:00:00Z', observed_at='2025-09-01T21:00:00Z', source='fixture',
                    line_convention='home_expected_margin', home_line='3')
        self.assertEqual(market_backtest([game], [line])['joined_games'], 1)
        for update in ({'home_id': 'B'}, {'line_convention': 'home_spread'}, {'quoted_at': ''},
                       {'observed_at': '2025-09-02T17:00:00Z'}, {'kickoff': '2025-09-03T18:00:00Z'}, {'home_line': 'nan'}):
            self.assertEqual(market_backtest([game], [{**line, **update}])['joined_games'], 0)
        self.assertEqual(market_backtest([game], [line, line])['rejected'], {'duplicate_quote': 1})
