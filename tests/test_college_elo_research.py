"""Research invariants; these do not enable ratings in the application."""
from dataclasses import replace
import unittest

from scripts.compare_college_elo import Game, bounded_residual, parse_season, replay, select_candidates


def game(gid, day, home='a', away='b', score=(35, 7), season=2020, divisions=('fbs', 'fbs')):
    return Game(gid, season, 1, day + 'T12:00:00+00:00', day, home, away, home, away,
                *divisions, *score, True, 'regular')


CONFIG = dict(family='tanh', alpha=0.3, home=2, cap=21, retention=0.25)


class CollegeEloResearchTests(unittest.TestCase):
    def test_narrow_win_can_lower_rating_and_loss_can_raise_it(self):
        history = [game(str(i), f'2020-09-{i:02}', score=(56, 0)) for i in range(1, 8)]
        history.append(game('8', '2020-09-08', score=(21, 20)))
        row = replay(history, CONFIG)[-1]
        self.assertGreater(row['benchmark'], 1)
        self.assertLess(row['home_change'], 0)
        self.assertGreater(row['away_after'], row['away_before'])
        self.assertAlmostEqual(row['home_before'] + row['away_before'], row['home_after'] + row['away_after'])

    def test_blowout_influence_is_bounded_and_monotonic(self):
        for family in ('clip', 'tanh'):
            values = [bounded_residual(x, family, 21) for x in (-1000, -28, 0, 28, 1000)]
            self.assertEqual(values, sorted(values))
            self.assertTrue(all(abs(x) <= 21 for x in values))
            self.assertEqual(values[2], 0)
            self.assertAlmostEqual(values[0], -values[-1])

    def test_results_on_one_date_cannot_influence_other_predictions_on_that_date(self):
        history = [game('1', '2020-09-01'), game('2', '2020-09-01', 'c', 'd'),
                   game('3', '2020-09-08', 'a', 'c')]
        self.assertEqual(replay(history, CONFIG), replay(history, CONFIG, reverse_day=True))

    def test_future_results_do_not_change_prior_ratings(self):
        history = [game('1', '2020-09-01'), game('2', '2020-09-08')]
        original = replay(history, CONFIG)
        altered = replay([history[0], replace(history[1], home_score=0, away_score=99)], CONFIG)
        self.assertEqual(original[0], altered[0])
        self.assertEqual(original[1]['benchmark'], altered[1]['benchmark'])
        self.assertNotEqual(original[1]['home_after'], altered[1]['home_after'])

    def test_spring_games_do_not_trigger_a_second_offseason(self):
        history = [game('1', '2020-09-01', divisions=('fcs', 'fcs')),
                   replace(game('2', '2021-03-01', season=2020, divisions=('fcs', 'fcs')), phase='spring_regular'),
                   game('3', '2021-09-01', season=2021, divisions=('fcs', 'fcs'))]
        rows = replay(history, CONFIG)
        self.assertEqual(rows[1]['home_before'], rows[0]['home_after'])
        self.assertAlmostEqual(rows[2]['home_before'], rows[1]['home_after'] * 0.25)

    def test_division_change_does_not_gift_the_new_division_mean(self):
        history = [game('1', '2020-09-01', divisions=('fbs', 'fcs')),
                   game('2', '2021-09-01', divisions=('fbs', 'fbs'))]
        rows = replay(history, CONFIG)
        # Each old division contains one team: both shrink toward themselves.
        self.assertEqual(rows[1]['away_before'], rows[0]['away_after'])
        self.assertLess(rows[1]['away_before'], rows[1]['division_centers']['fbs'])

    def test_source_rejects_ambiguous_identity_and_unplayed_zero_scores(self):
        row = {'game_id': '123', 'season': '2020', 'week': '1', 'season_type': 'regular',
               'start_date': '2020-09-01T12:00:00Z', 'neutral_site': 'false', 'completed': 'true',
               'status': 'STATUS_FINAL', 'home_id': '1', 'away_id': '2', 'home_team': 'A', 'away_team': 'B',
               'home_division': 'fbs', 'away_division': 'fcs', 'home_points': '21', 'away_points': '7'}
        with self.assertRaises(ValueError):
            parse_season([row, row], 2020)
        with self.assertRaisesRegex(ValueError, 'twice'):
            parse_season([row, {**row, 'game_id': '999'}], 2020)
        with self.assertRaises(ValueError):
            parse_season([{**row, 'completed': 'false', 'status': 'STATUS_SCHEDULED', 'home_points': '0', 'away_points': '0'}], 2020)
        parsed, audit = parse_season([row, {**row, 'game_id': '124', 'completed': 'false', 'status': 'STATUS_CANCELED'}], 2020)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(audit['exclusions_and_notices']['canceled'], 1)

    def test_selection_cannot_receive_held_out_games(self):
        with self.assertRaisesRegex(ValueError, 'Held-out'):
            select_candidates([game('1', '2022-09-01', season=2022)], {'selection_seasons': [2017, 2021]})

    def test_corrections_replay_once_and_repeat_reads_are_identical(self):
        original = [game('1', '2020-09-01'), game('2', '2020-09-08')]
        corrected = [replace(original[0], home_score=0, away_score=35), original[1]]
        self.assertEqual(replay(corrected, CONFIG), replay(corrected, CONFIG))
        self.assertNotEqual(replay(original, CONFIG)[1]['benchmark'], replay(corrected, CONFIG)[1]['benchmark'])

    def test_venue_adjustment_is_removed_at_neutral_sites(self):
        neutral = game('1', '2020-09-01')
        self.assertEqual(replay([neutral], CONFIG)[0]['benchmark'], 0)
        self.assertEqual(replay([replace(neutral, neutral=False)], CONFIG)[0]['benchmark'], 2)


if __name__ == '__main__':
    unittest.main()
