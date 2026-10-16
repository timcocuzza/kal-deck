from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from backend.catalog import RefreshService
from backend.props import PROP_TYPES, build_player_log, build_props
from backend.sources.common import Resource, SourceData, SourceError
from backend.sources.kalshi_metadata import load_players
from backend.storage import SnapshotStore
from test_matchups import fixtures, AWAY, NOW

PLAYER = '00000000-0000-0000-0000-000000000004'
GSIS = '00-0000001'


def prop_fixtures(category='receiving_yards'):
    schedule, _, milestones, targets = fixtures()
    series, _, statistic, _, _ = PROP_TYPES[category]
    event = series + '-26OCT15SEADEN'
    milestones[0]['related_event_tickers'].append(event)
    milestones[0]['details']['player_id_mapping'] = {'provider-player': PLAYER}
    market = {'ticker': event + '-PLAYER-50', 'event_ticker': event, 'market_type': 'binary',
              'status': 'active', 'strike_type': 'greater', 'floor_strike': 49.5,
              'custom_strike': {'football_player': PLAYER, 'football_team': AWAY},
              'title': f'Test Player: 50+ {statistic}', 'yes_sub_title': 'Test Player: 50+',
              'rules_primary': f'If Test Player records 50+ {statistic} in the Seattle vs Denver Pro Football game originally scheduled for Oct 15, 2026, then the market resolves to Yes.',
              'rules_secondary': 'Participation conditions.', 'yes_bid_dollars': '.40', 'yes_ask_dollars': '.44',
              'no_bid_dollars': '.56', 'no_ask_dollars': '.60'}
    players = [{'id': PLAYER, 'type': 'football_player', 'name': 'Test Player',
                'details': {'league': 'NFL', 'team_id': AWAY, 'position': 'WR'}}]
    stats = [{'season': '2026', 'season_type': 'REG', 'player_id': GSIS,
              'player_display_name': 'Test Player', 'team': 'SEA', 'position': 'WR'}]
    return [schedule, [market], milestones, targets, players, stats, []]


def run_props(parts):
    return build_props(2026, '2026_06_SEA_DEN', *parts, now=NOW)


class PropTests(unittest.TestCase):
    def test_all_approved_categories_verify_original_rules(self):
        for category in PROP_TYPES:
            with self.subTest(category=category):
                result = run_props(prop_fixtures(category))
                self.assertEqual(result['issues'], [])
                group = result['groups'][0]
                self.assertEqual(group['category'], category)
                self.assertEqual(group['player']['id'], GSIS)
                self.assertEqual(group['markets'][0]['threshold'], 50)
                self.assertEqual(group['markets'][0]['midpoint'], .42)
                self.assertEqual(group['markets'][0]['rules_secondary'], 'Participation conditions.')

    def test_sport_wording_variants_preserve_exact_names(self):
        parts = prop_fixtures('rushing_yards')
        parts[1][0]['rules_primary'] = parts[1][0]['rules_primary'].replace('Pro Football', 'professional football')
        self.assertEqual(run_props(parts)['issues'], [])
        parts[1][0]['rules_primary'] = parts[1][0]['rules_primary'].replace('Test Player', 'test player')
        self.assertFalse(run_props(parts)['groups'])

    def test_no_fuzzy_names_or_position_guesses(self):
        for mutate in [lambda p: p[5][0].update(player_display_name='Test Player Jr.'),
                       lambda p: p[5][0].update(position='TE'),
                       lambda p: p[5][0].update(team='DEN'),
                       lambda p: p[5].append({**p[5][0], 'player_id': '00-0000002'})]:
            parts = prop_fixtures(); mutate(parts)
            result = run_props(parts)
            self.assertFalse(result['groups']); self.assertTrue(result['issues'])

    def test_latest_depth_can_match_player_without_game_stats(self):
        parts = prop_fixtures(); parts[5].clear()
        parts[6] = [{'player_name': 'Test Player', 'team': 'SEA', 'gsis_id': GSIS,
                     'pos_abb': 'WR', 'dt': '2026-10-15'},
                    {'player_name': 'Test Player', 'team': 'SEA', 'gsis_id': 'old-id',
                     'pos_abb': 'WR', 'dt': '2026-09-01'}]
        self.assertEqual(run_props(parts)['groups'][0]['player']['id'], GSIS)

    def test_wrong_player_team_game_or_settlement_withholds_quote(self):
        mutations = [lambda p: p[1][0]['custom_strike'].update(football_team=p[3][0]['id']),
                     lambda p: p[2][0]['details']['player_id_mapping'].clear(),
                     lambda p: p[1][0].update(floor_strike=50.5),
                     lambda p: p[1][0].update(title='Different Player: 50+ receiving yards'),
                     lambda p: p[1][0].update(status='settled'),
                     lambda p: p[1][0].update(market_type='scalar'),
                     lambda p: p[1][0].update(cap_strike=60),
                     lambda p: p[1][0].update(rules_primary=p[1][0]['rules_primary'].replace('Oct 15', 'Oct 18')),
                     lambda p: p[1][0].update(rules_primary=p[1][0]['rules_primary'].replace('receiving yards', 'rushing yards'))]
        for mutate in mutations:
            parts = prop_fixtures(); mutate(parts); result = run_props(parts)
            self.assertFalse(result['groups']); self.assertTrue(result['issues'])

    def test_ambiguous_player_identity_withholds_contract(self):
        parts = prop_fixtures(); parts[4].append(deepcopy(parts[4][0]))
        self.assertFalse(run_props(parts)['groups'])

    def test_schedule_conflict_and_duplicate_milestone_do_not_match(self):
        for mutate in [lambda p: p[2][0].update(start_date='2026-10-16T01:15:00Z'),
                       lambda p: p[2].append(deepcopy(p[2][0])),
                       lambda p: p[3].append(deepcopy(p[3][0])),
                       lambda p: p[0].append({**p[0][0], 'game_id': 'duplicate-schedule-game'})]:
            parts = prop_fixtures(); mutate(parts); result = run_props(parts)
            self.assertFalse(result['groups']); self.assertTrue(result['warnings'])

    def test_started_games_have_no_props(self):
        parts = prop_fixtures()
        result = build_props(2026, '2026_06_SEA_DEN', *parts,
                             now=datetime(2026, 10, 16, 0, 15, tzinfo=timezone.utc))
        self.assertFalse(result['groups']); self.assertTrue(result['warnings'])

    def test_unavailable_quotes_and_broken_contract_do_not_hide_valid_choice(self):
        parts = prop_fixtures(); parts[1][0].update(yes_bid_dollars='0', no_ask_dollars='NaN')
        broken = deepcopy(parts[1][0]); broken.update(ticker='bad', custom_strike=None)
        parts[1].append(broken)
        result = run_props(parts)
        self.assertEqual(len(result['groups']), 1); self.assertEqual(len(result['issues']), 1)
        market = result['groups'][0]['markets'][0]
        self.assertIsNone(market['midpoint']); self.assertIsNone(market['no_ask_dollars'])

    def test_thresholds_sort_numerically_and_other_events_are_not_imported(self):
        parts = prop_fixtures(); other = deepcopy(parts[1][0])
        other.update(ticker=other['ticker'] + 'x', floor_strike=9.5,
                     title=other['title'].replace('50+', '10+'), yes_sub_title='Test Player: 10+',
                     rules_primary=other['rules_primary'].replace('50+', '10+'))
        parts[1].append(other)
        wrong_game = deepcopy(other); wrong_game['event_ticker'] += '-OTHER'; parts[1].append(wrong_game)
        wrong_game['ticker'] += '-OTHER'
        self.assertEqual([m['threshold'] for m in run_props(parts)['groups'][0]['markets']], [10, 50])

    def test_unsupported_links_are_disclosed_without_claiming_open_quotes(self):
        parts = prop_fixtures(); parts[2][0]['related_event_tickers'].append('KXNFLFIRSTTD-26OCT15SEADEN')
        result = run_props(parts)
        self.assertEqual(result['unsupported'][0]['series'], 'KXNFLFIRSTTD')

    def test_duplicate_contract_and_ambiguous_event_are_flagged(self):
        parts = prop_fixtures(); parts[1].append(deepcopy(parts[1][0]))
        self.assertFalse(run_props(parts)['groups'])
        parts = prop_fixtures(); other = deepcopy(parts[2][0]); other['details']['season']['week'] = 7
        parts[2].append(other)
        self.assertFalse(run_props(parts)['groups'])


class PlayerLogTests(unittest.TestCase):
    def setUp(self):
        self.schedule = [{'season': '2026', 'game_type': 'REG', 'week': '1', 'game_id': 'g1',
                          'home_team': 'DEN', 'away_team': 'SEA', 'gameday': '2026-09-01',
                          'home_score': '7', 'away_score': '10'}]
        self.stats = [{'season': '2026', 'season_type': 'REG', 'week': '1', 'game_id': 'g1',
                       'player_id': GSIS, 'team': 'SEA', 'opponent_team': 'DEN',
                       'receiving_yards': '50', 'rushing_yards': '10'}]
        self.ranks = [{'team': 'DEN', 'categories': {'passing_defense': {'headline': {'rank': 3, 'incomplete': False}},
                                                   'rushing_defense': {'headline': {'rank': 7, 'incomplete': True}}}}]

    def log(self, category='receiving_yards'):
        return build_player_log(2026, GSIS, category, self.schedule, self.stats, self.ranks)

    def test_combined_values_and_two_current_ranks(self):
        row = self.log('rushing_receiving_yards')['games'][0]
        self.assertEqual(row['value'], 60)
        self.assertEqual([r['rank'] for r in row['opponent_ranks']], [7, 3])
        self.assertTrue(row['opponent_ranks'][0]['incomplete'])

    def test_missing_component_is_unknown_not_zero(self):
        self.stats[0]['rushing_yards'] = ''
        self.assertIsNone(self.log('rushing_receiving_yards')['games'][0]['value'])
        self.stats[0]['rushing_yards'] = '0'
        self.assertEqual(self.log('rushing_receiving_yards')['games'][0]['value'], 50)

    def test_follows_id_across_teams_but_not_other_seasons_or_playoffs(self):
        self.stats.append({**self.stats[0], 'game_id': 'g2', 'week': '2', 'team': 'BUF', 'receiving_yards': '20'})
        self.schedule.append({**self.schedule[0], 'game_id': 'g2', 'week': '2', 'away_team': 'BUF', 'gameday': '2026-09-08'})
        self.stats.extend([{**self.stats[0], 'season': '2025'}, {**self.stats[0], 'season_type': 'POST'},
                           {**self.stats[0], 'player_id': 'another-player'}])
        self.assertEqual([r['team'] for r in self.log()['games']], ['BUF', 'SEA'])

    def test_absent_game_rows_are_not_invented(self):
        self.schedule.append({**self.schedule[0], 'game_id': 'g2', 'week': '2'})
        self.assertEqual(len(self.log()['games']), 1)
        self.stats.clear(); self.assertEqual(self.log()['games'], [])

    def test_conflicting_duplicate_or_uncompleted_games_are_withheld(self):
        original = deepcopy(self.stats)
        for change in [lambda: self.stats[0].update(opponent_team='DAL'),
                       lambda: self.stats.append(deepcopy(self.stats[0])),
                       lambda: self.schedule[0].update(home_score='')]:
            self.stats = deepcopy(original); change(); result = self.log()
            self.assertFalse(result['games']); self.assertTrue(result['warnings'])

    def test_missing_rank_preserves_stats(self):
        self.ranks.clear(); row = self.log()['games'][0]
        self.assertEqual(row['value'], 50); self.assertIsNone(row['opponent_ranks'][0]['rank'])


class PlayerSourceTests(unittest.TestCase):
    def test_paginated_identities_and_failed_refresh_retains_previous_snapshot(self):
        player = prop_fixtures()[4][0]
        def fetch(url):
            data = {'structured_targets': [] if 'cursor=next' in url else [player],
                    'cursor': '' if 'cursor=next' in url else 'next'}
            return Resource(json.dumps(data).encode(), url, '2026-10-15T00:00:00Z')
        data = load_players(fetch)
        self.assertEqual(data.rows, [player])
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / 'cache.sqlite3'); store.initialize(); store.save('kalshi_players', data)
            def fail(url):
                raise SourceError('Source returned HTTP 429.')
            result = RefreshService(store, fail).refresh('kalshi_players', 2026)
            self.assertEqual(result['error'], 'Source returned HTTP 429.')
            self.assertEqual(store.read('kalshi_players').rows, [player])

    def test_malformed_identity_is_rejected(self):
        player = prop_fixtures()[4][0]; player['details']['league'] = 'NBA'
        with self.assertRaises(SourceError):
            load_players(lambda url: Resource(json.dumps({'structured_targets': [player]}).encode(), url, 'now'))


if __name__ == '__main__':
    unittest.main()
