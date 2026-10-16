from copy import deepcopy
import math
import unittest

from backend.elo import EloConfig, expected_score, margin_multiplier, prepare_elo_history, replay_elo
from backend.sources.common import SourceError


CONFIG = EloConfig(20, 65, 2 / 3)


def game(gid='g1', season=2002, home='A', away='B', score=(20, 10), neutral=True):
    return {'game_id': gid, 'season': season, 'phase': 'REG', 'kickoff': f'{season}-09-01T20:00:00+00:00',
            'home_team': home, 'away_team': away, 'home_score': score[0], 'away_score': score[1], 'neutral': neutral}


def raw_season(year=2002):
    return [{'game_id': f'{year}-{i}', 'season': str(year), 'game_type': 'REG', 'gameday': f'{year}-09-01',
             'gametime': '13:00', 'home_team': f'T{i}', 'away_team': f'T{i+16}',
             'home_score': '20', 'away_score': '10', 'location': 'Home'} for i in range(16)]


class EloTests(unittest.TestCase):
    def test_logistic_symmetry_and_stable_extremes(self):
        self.assertEqual(expected_score(0), 0.5)
        self.assertAlmostEqual(expected_score(400), 10 / 11)
        self.assertAlmostEqual(expected_score(65) + expected_score(-65), 1)
        self.assertEqual(expected_score(1e6), 1)
        self.assertEqual(expected_score(-1e6), 0)

    def test_neutral_site_removes_home_advantage(self):
        neutral = replay_elo([game()], CONFIG)['games'][0]
        home = replay_elo([game(neutral=False)], CONFIG)['games'][0]
        self.assertEqual(neutral['home_expected_score'], 0.5)
        self.assertAlmostEqual(home['home_expected_score'], 1 / (1 + 10 ** (-65 / 400)))
        self.assertGreater(neutral['home_change'], home['home_change'])

    def test_forecast_precedes_result_and_rating_updates_are_zero_sum(self):
        first = replay_elo([game()], CONFIG)
        reverse = replay_elo([game(score=(10, 20))], CONFIG)
        self.assertEqual(first['games'][0]['home_expected_score'], reverse['games'][0]['home_expected_score'])
        self.assertGreater(first['ratings']['A'], 1500)
        self.assertLess(first['ratings']['B'], 1500)
        self.assertAlmostEqual(sum(first['ratings'].values()), 3000)
        self.assertEqual(first['games'][0]['home_change'], -first['games'][0]['away_change'])

    def test_upsets_gain_more_than_expected_wins(self):
        seed = game(score=(40, 0))
        expected = replay_elo([seed, game('g2', score=(20, 10))], CONFIG)['games'][1]
        upset = replay_elo([seed, game('g2', score=(10, 20))], CONFIG)['games'][1]
        self.assertGreater(abs(upset['home_change']), expected['home_change'])

    def test_margin_grows_with_diminishing_returns_and_corrects_opponent_strength(self):
        one, ten, twenty = [margin_multiplier(value, 0, 0) for value in (1, 10, 20)]
        self.assertLess(one, ten)
        self.assertLess(ten, twenty)
        self.assertLess(twenty - ten, ten - one)
        self.assertLess(margin_multiplier(20, 10, 200), margin_multiplier(20, 10, -200))
        with self.assertRaises(SourceError):
            margin_multiplier(20, 10, -2200)

    def test_ties_use_half_credit_and_do_not_imply_a_draw_probability(self):
        tied = replay_elo([game(score=(20, 20))], CONFIG)['games'][0]
        self.assertEqual(tied['home_result'], 0.5)
        self.assertEqual(tied['home_change'], 0)
        self.assertAlmostEqual(tied['margin_multiplier'], 2.2 * math.log(2))
        home = replay_elo([game(score=(20, 20), neutral=False)], CONFIG)['games'][0]
        self.assertLess(home['home_change'], 0)

    def test_offseason_regression_applies_once_and_preserves_center(self):
        first = replay_elo([game()], CONFIG)
        result = replay_elo([game(), game('g2', season=2003), game('g3', season=2003)], CONFIG)
        opening = result['season_openings'][2003]
        self.assertAlmostEqual(opening['A'], 1500 + (first['ratings']['A'] - 1500) * 2 / 3)
        self.assertEqual(result['games'][1]['home_rating_before'], opening['A'])
        self.assertEqual(result['games'][2]['home_rating_before'], result['games'][1]['home_rating_after'])
        self.assertAlmostEqual(sum(result['ratings'].values()), 3000)

    def test_historical_preparation_filters_future_seasons_and_excludes_preseason(self):
        rows = raw_season() + raw_season(2003) + raw_season(2026)
        rows.append({**rows[0], 'game_id': 'pre', 'game_type': 'PRE'})
        prepared = prepare_elo_history(list(reversed(rows)), 2002, 2003)
        self.assertEqual(len(prepared), 32)
        self.assertEqual({row['season'] for row in prepared}, {2002, 2003})
        self.assertEqual(prepared[0]['season'], 2002)

    def test_relocations_preserve_franchise_identity(self):
        rows = raw_season(2002) + raw_season(2003)
        rows[0]['home_team'] = 'OAK'
        rows[16]['home_team'] = 'LV'
        prepared = prepare_elo_history(rows, 2002, 2003)
        self.assertEqual(sum(row['home_team'] == 'LV' for row in prepared), 2)
        self.assertNotIn('OAK', replay_elo(prepared, CONFIG)['ratings'])

    def test_missing_seasons_scores_venue_and_duplicate_games_are_rejected(self):
        rows = raw_season()
        with self.assertRaises(SourceError):
            prepare_elo_history(rows, 2002, 2003)
        with self.assertRaises(SourceError):
            prepare_elo_history(rows + rows, 2002, 2002)
        for changes in ({'home_score': ''}, {'away_score': '-1'}, {'location': ''}, {'gametime': ''},
                        {'home_score': 'NaN'}, {'game_type': 'UNKNOWN'}, {'away_team': rows[0]['home_team']}):
            changed = deepcopy(rows)
            changed[0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(SourceError):
                prepare_elo_history(changed, 2002, 2002)

    def test_missing_franchise_and_two_games_on_one_day_are_rejected(self):
        rows = raw_season()
        with self.assertRaises(SourceError):
            prepare_elo_history(rows[:-1], 2002, 2002)
        rows.append({**rows[0], 'game_id': 'duplicate-matchup'})
        with self.assertRaises(SourceError):
            prepare_elo_history(rows, 2002, 2002)

    def test_invalid_parameters_fail_before_replay(self):
        for values in ((0, 65, .5), (20, float('nan'), .5), (20, 65, 2), (True, 65, .5)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                EloConfig(*values)


if __name__ == '__main__':
    unittest.main()
