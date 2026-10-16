from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from backend.catalog import RefreshService
from backend.matchups import build_matchups, kickoff, research_for_team
from backend.sources.common import Resource, SourceData, SourceError
from backend.sources.kalshi_metadata import load_games, load_teams
from backend.storage import SnapshotStore

HOME = '00000000-0000-0000-0000-000000000001'
AWAY = '00000000-0000-0000-0000-000000000002'
EVENT = 'KXNFLSPREAD-26OCT15SEADEN'
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def fixtures():
    games = [{'game_id': '2026_06_SEA_DEN', 'season': '2026', 'game_type': 'REG', 'week': '6',
              'gameday': '2026-10-15', 'gametime': '20:15', 'home_team': 'DEN', 'away_team': 'SEA',
              'home_score': '', 'away_score': '', 'location': 'Home'}]
    targets = [{'id': identifier, 'name': name, 'type': 'football_team',
                'details': {'abbreviation': code, 'league': 'NFL', 'image_url': f'https://assets.kalshi.com/structured_targets/NFL_{code}.webp'}}
               for identifier, name, code in [(HOME, 'Denver', 'DEN'), (AWAY, 'Seattle', 'SEA')]]
    milestone = {'id': '00000000-0000-0000-0000-000000000003', 'type': 'football_game',
                 'start_date': '2026-10-16T00:15:00Z', 'primary_event_tickers': [EVENT],
                 'related_event_tickers': [EVENT],
                 'details': {'league': 'NFL', 'home_team_id': HOME, 'away_team_id': AWAY,
                             'season': {'year': 2026, 'type': 'REG', 'week': 6}}}
    market = {'ticker': EVENT + '-SEA3', 'event_ticker': EVENT, 'market_type': 'binary',
              'strike_type': 'greater', 'floor_strike': 2.5, 'custom_strike': {'football_team': AWAY},
              'title': 'Seattle wins by over 2.5 points?', 'yes_sub_title': 'Seattle wins by over 2.5 points',
              'rules_primary': 'If Seattle wins by more than 2.5 points in the Seattle vs Denver Pro Football game originally scheduled for Oct 15, 2026, then the market resolves to Yes.',
              'yes_bid_dollars': '0.49', 'yes_ask_dollars': '0.51', 'no_bid_dollars': '0.49', 'no_ask_dollars': '0.51', 'volume_fp': '10'}
    return games, [market], [milestone], targets


def run_case(parts, **kwargs):
    return build_matchups(2026, *parts, week=6, now=NOW, **kwargs)


class MatchupTests(unittest.TestCase):
    def test_unique_verified_match_and_spread_meaning(self):
        result = run_case(fixtures())
        game = result['games'][0]
        self.assertEqual(result['issues'], [])
        self.assertEqual(game['default_market_ticker'], EVENT + '-SEA3')
        self.assertEqual(game['markets'][0]['label'], 'SEA −2.5')
        self.assertEqual(game['markets'][0]['spread'], -2.5)
        self.assertEqual(game['markets'][0]['midpoint'], .5)
        self.assertEqual(game['kickoff'], '2026-10-16T00:15:00+00:00')

    def test_clock_hides_started_games_even_if_market_is_open(self):
        parts = fixtures()
        result = build_matchups(2026, *parts, week=6, now=datetime(2026, 10, 16, 0, 15, tzinfo=timezone.utc))
        self.assertEqual(result['games'], [])
        winter = {**parts[0][0], 'gameday': '2026-12-01'}
        self.assertEqual(kickoff(winter).hour, 1)  # EST rather than EDT.

    def test_unknown_kickoff_keeps_game_without_prices(self):
        parts = fixtures(); parts[0][0]['gametime'] = ''
        result = run_case(parts)
        self.assertEqual(len(result['games']), 1)
        self.assertIsNone(result['games'][0]['kickoff'])
        self.assertEqual(result['games'][0]['markets'], [])
        self.assertTrue(result['issues'])

    def test_no_market_keeps_scheduled_game_visible(self):
        parts = fixtures(); parts[1].clear()
        result = run_case(parts)
        self.assertEqual(result['games'][0]['spread_status'], 'Spread unavailable')

    def test_kickoff_team_week_and_season_conflicts_withhold_prices(self):
        mutations = [lambda m: m.update(start_date='2026-10-16T01:15:00Z'),
                     lambda m: m['details'].update(home_team_id=AWAY, away_team_id=HOME),
                     lambda m: m['details']['season'].update(week=7),
                     lambda m: m['details']['season'].update(year=2025)]
        for change in mutations:
            parts = fixtures(); change(parts[2][0]); result = run_case(parts)
            self.assertEqual(result['games'][0]['markets'], [])
            self.assertTrue(result['issues'])

    def test_missing_or_ambiguous_identity_never_guesses(self):
        for duplicate in [False, True]:
            parts = fixtures()
            if duplicate:
                other = deepcopy(parts[2][0]); other['id'] = 'other'; parts[2].append(other)
            else: parts[2].clear()
            result = run_case(parts)
            self.assertEqual(result['games'][0]['markets'], [])
            self.assertTrue(result['issues'])

    def test_wrong_contract_team_strike_title_or_rules_is_flagged(self):
        mutations = [lambda m: m['custom_strike'].update(football_team=HOME),
                     lambda m: m.update(floor_strike=3.5), lambda m: m.update(title='Different wording'),
                     lambda m: m.update(rules_primary=m['rules_primary'].replace('2.5', '9.5')),
                     lambda m: m.update(rules_primary=m['rules_primary'].replace('Oct 15', 'Oct 18')),
                     lambda m: m.update(rules_primary=m['rules_primary'].replace('Seattle vs Denver', 'Seattle vs Dallas'))]
        for change in mutations:
            parts = fixtures(); change(parts[1][0]); result = run_case(parts)
            self.assertEqual(result['games'][0]['markets'], [])
            self.assertEqual(result['issues'][0]['market'], EVENT + '-SEA3')

    def test_missing_quotes_remain_selectable_without_becoming_default(self):
        parts = fixtures(); parts[1][0]['yes_bid_dollars'] = '0'
        game = run_case(parts)['games'][0]
        self.assertEqual(len(game['markets']), 1)
        self.assertIsNone(game['default_market_ticker'])
        self.assertIsNone(game['markets'][0]['yes_bid_dollars'])
        self.assertIsNone(game['markets'][0]['midpoint'])

    def test_malformed_contract_does_not_hide_other_verified_contracts(self):
        parts = fixtures()
        broken = deepcopy(parts[1][0]); broken.update(ticker=EVENT + '-BROKEN', custom_strike=None)
        parts[1].append(broken)
        result = run_case(parts)
        self.assertEqual(len(result['games'][0]['markets']), 1)
        self.assertEqual(result['games'][0]['default_market_ticker'], EVENT + '-SEA3')
        self.assertEqual(len(result['issues']), 1)

    def test_aliases_and_designated_home_team_at_neutral_site(self):
        parts = fixtures()
        parts[0][0].update(home_team='JAX', location='Neutral')
        parts[3][0].update(name='Jacksonville')
        parts[3][0]['details']['abbreviation'] = 'JAC'
        parts[1][0]['rules_primary'] = parts[1][0]['rules_primary'].replace('Denver', 'Jacksonville')
        result = run_case(parts)
        self.assertEqual(result['issues'], [])
        self.assertTrue(result['games'][0]['neutral'])
        self.assertEqual(result['games'][0]['home']['code'], 'JAX')
        parts[0][0]['home_team'] = 'LA'; parts[3][0]['name'] = 'Los Angeles R'
        parts[3][0]['details']['abbreviation'] = 'LAR'
        parts[1][0]['rules_primary'] = parts[1][0]['rules_primary'].replace('Jacksonville', 'Los Angeles R')
        self.assertEqual(run_case(parts)['issues'], [])

    def test_injuries_require_matching_week_and_blanks_stay_unknown(self):
        injury = SourceData([{'team_name': 'Seahawks', 'player_name': 'Player', 'game_status': None}], 'url', 'date',
                            context={'season': 2026, 'week': 6, 'reported_teams': ['Seahawks']})
        result = research_for_team('SEA', 2026, 6, None, injury, None)
        self.assertTrue(result['injuries_available']); self.assertIsNone(result['injuries'][0]['game_status'])
        result = research_for_team('SEA', 2026, 7, None, injury, None)
        self.assertFalse(result['injuries_available']); self.assertEqual(result['injuries'], [])


class MetadataTests(unittest.TestCase):
    def test_team_placeholder_excluded_with_visible_warning(self):
        targets = fixtures()[3] + [{'id': '00000000-0000-0000-0000-000000000004', 'name': 'Retires / No Team',
                                   'type': 'football_team', 'details': {'league': 'NFL'}}]
        def fetch(url): return Resource(json.dumps({'structured_targets': targets, 'cursor': ''}).encode(), url, 'now')
        result = load_teams(fetch)
        self.assertEqual(len(result.rows), 2); self.assertTrue(result.warnings)

    def test_event_lookup_and_missing_link_reporting(self):
        milestone = fixtures()[2][0]
        def fetch(url):
            self.assertIn('related_event_ticker=', url)
            return Resource(json.dumps({'milestones': [milestone], 'cursor': ''}).encode(), url, 'now')
        result = load_games(2026, [EVENT], fetch)
        self.assertEqual(result.rows, [milestone])
        def missing(url): return Resource(b'{"milestones":[],"cursor":""}', url, 'now')
        self.assertTrue(load_games(2026, [EVENT], missing).warnings)

    def test_invalid_metadata_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SnapshotStore(Path(folder) / 'test.sqlite3'); store.initialize()
            store.save('spreads', SourceData(fixtures()[1], 'url', 'old'))
            store.save('kalshi_games:2026', SourceData(fixtures()[2], 'url', 'old'))
            def fetch(url): return Resource(b'{"milestones":[{}],"cursor":""}', url, 'now')
            result = RefreshService(store, fetch).refresh('kalshi_games', 2026)
            self.assertEqual(result['status'], 'refresh_failed')
            self.assertEqual(store.read('kalshi_games:2026').rows, fixtures()[2])


if __name__ == '__main__':
    unittest.main()
