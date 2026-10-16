import unittest
from fractions import Fraction

from backend.rankings import calculate_rankings, assign_ranks, league_summary, CATEGORIES
from backend.sources.common import SourceError


def game(key='g1', home='A', away='B', week=1, **extra):
    return {'game_id': key, 'season': '2026', 'game_type': 'REG', 'week': str(week),
            'gameday': f'2026-09-{week:02}', 'home_team': home, 'away_team': away,
            'home_score': '14', 'away_score': '7', **extra}


def play(key, game_id='g1', offense='A', defense='B', epa='1', kind='pass', **extra):
    return {'play_id': str(key), 'game_id': game_id, 'season': '2026', 'season_type': 'REG',
            'posteam': offense, 'defteam': defense, 'epa': epa, 'pass': str(int(kind == 'pass')),
            'rush': str(int(kind == 'run')), 'play_type': kind, **extra}


def chart(key, count, game_id='g1', **extra):
    return {'nflverse_play_id': str(key), 'nflverse_game_id': game_id, 'season': '2026',
            'n_blitzers': str(count), **extra}


def stats(game_id='g1', team='A', opponent='B', **extra):
    return {'game_id': game_id, 'season': '2026', 'season_type': 'REG', 'team': team,
            'opponent_team': opponent, 'passing_yards': '100', 'attempts': '10',
            'completions': '5', 'passing_tds': '1', 'passing_interceptions': '0',
            'rushing_yards': '50', 'carries': '10', 'rushing_tds': '1',
            'def_sacks': '2', 'sacks_suffered': '3', **extra}


def team(report, name='A'):
    return next(t for t in report['teams'] if t['team'] == name)


def headline(report, name='A', category='passing_offense'):
    return team(report, name)['categories'][category]['headline']


class RankingTests(unittest.TestCase):
    def test_league_mean_and_median_odd_even_and_unavailable_values(self):
        metrics = [{'value': Fraction(value), 'incomplete': False} for value in [0, 2, 10]]
        odd = league_summary(metrics)
        self.assertEqual((odd['mean'], odd['median']), (4, 2))
        self.assertFalse(odd['incomplete'])
        even = league_summary(metrics + [{'value': Fraction(20), 'incomplete': False}])
        self.assertEqual((even['mean'], even['median']), (8, 6))
        missing = league_summary(metrics + [{'value': None, 'incomplete': True}])
        self.assertEqual((missing['mean'], missing['median']), (4, 2))
        self.assertEqual((missing['teams_used'], missing['teams_expected']), (3, 4))
        self.assertTrue(missing['incomplete'])

    def test_league_context_flags_partial_values_and_handles_empty_data(self):
        partial = league_summary([{'value': Fraction(1, 3), 'incomplete': True},
                                  {'value': Fraction(2, 3), 'incomplete': False}])
        self.assertEqual((partial['mean'], partial['median']), (Fraction(1, 2), Fraction(1, 2)))
        self.assertTrue(partial['incomplete'])
        self.assertEqual(partial['teams_used'], 2)
        for metrics in ([], [{'value': None, 'incomplete': True}]):
            empty = league_summary(metrics)
            self.assertIsNone(empty['mean'])
            self.assertIsNone(empty['median'])
            self.assertTrue(empty['incomplete'])

    def test_league_context_weights_team_season_values_not_games_or_plays(self):
        report = calculate_rankings(2026, [game(), game('g2', away='C', week=2)], [],
            [play(1, epa='0'), play(1, 'g2', defense='C', epa='2'),
             play(2, offense='B', defense='A', epa='6')],
            [chart(1, 0), chart(1, 1, 'g2'), chart(2, 0)])
        context = report['league']['categories']['passing_offense']
        self.assertEqual((context['mean'], context['median']), (3.5, 3.5))
        self.assertEqual((context['teams_used'], context['teams_expected']), (2, 3))
        self.assertEqual(set(report['league']['categories']), set(CATEGORIES))
        self.assertAlmostEqual(report['league']['blitz']['mean'], 100 / 3)
        self.assertEqual(report['league']['blitz']['median'], 0)

    def test_equal_game_weighting_instead_of_pooled_plays(self):
        report = calculate_rankings(2026, [game(), game('g2', week=2)], [],
                                    [play(1, epa='4'), play(2, 'g2', epa='0'), play(3, 'g2', epa='0'), play(4, 'g2', epa='0')], [])
        self.assertEqual(headline(report)['value'], 2)
        self.assertEqual(headline(report, 'B', 'passing_defense')['value'], 2)
        self.assertFalse(headline(report)['incomplete'])

    def test_classified_penalties_scrambles_sacks_overtime_and_exclusions(self):
        plays = [play(1, epa='1'), play(2, epa='3', play_type='no_play', penalty='1'),
                 play(3, epa='2', kind='run', qb_scramble='1'), play(4, epa='-2', kind='other', sack='1'),
                 play(5, epa='1', qtr='5'),
                 play(6, epa='100', kind='other', penalty='1', play_type='no_play'),
                 play(7, epa='100', qb_spike='1'), play(8, epa='100', qb_kneel='1'),
                 play(9, epa='100', two_point_attempt='1')]
        report = calculate_rankings(2026, [game()], [], plays, [])
        self.assertEqual(headline(report)['value'], 1)
        self.assertEqual(headline(report)['coverage']['samples_used'], 5)
        self.assertIsNone(headline(report, category='rushing_offense')['value'])

    def test_success_is_positive_epa_and_game_weighted(self):
        plays = [play(1, kind='run', epa='1'), play(2, 'g2', kind='run', epa='1'),
                 play(3, 'g2', kind='run', epa='0'), play(4, 'g2', kind='run', epa='-1'),
                 play(5, 'g2', kind='run', epa='-2')]
        report = calculate_rankings(2026, [game(), game('g2', week=2)], [], plays, [])
        support = team(report)['categories']['rushing_offense']['supporting']
        self.assertEqual(support['success_percentage']['value'], 62.5)
        self.assertEqual(headline(report, category='rushing_offense')['value'], .25)

    def test_blitz_uses_blitzers_not_rusher_count_and_reports_missing_charting(self):
        plays = [play(1), play(2), play(3), play(4, play_type='no_play'),
                 play(5, two_point_attempt='1'), play(6, qb_spike='1'),
                 play(7, 'g2'), play(8, 'g2')]
        charts = [chart(1, 1, n_pass_rushers='4'), chart(2, 0, n_pass_rushers='5'),
                  chart(4, 1), chart(5, 1), chart(6, 1), chart(7, 1, 'g2'), chart(8, 1, 'g2')]
        report = calculate_rankings(2026, [game(), game('g2', week=2)], [], plays, charts)
        blitz = team(report, 'B')['blitz']
        self.assertEqual(blitz['value'], 75)
        self.assertEqual(blitz['coverage']['samples_used'], 4)
        self.assertEqual(blitz['coverage']['samples_expected'], 5)
        self.assertTrue(blitz['incomplete'])
        self.assertEqual(blitz['rank'], 1)
        self.assertIsNone(team(report, 'A')['blitz']['rank'])

    def test_blitz_frequency_ranks_ties_zero_and_missing_charting(self):
        schedule, plays, charts = [], [], []
        for week, (defense, counts) in enumerate([
            ('B', [1, 1]), ('C', [1, 0]), ('D', [1, 0, None]),
            ('E', [0, 0]), ('F', [None, None]),
        ], 1):
            game_id = f'g{week}'
            schedule.append(game(game_id, away=defense, week=week))
            for play_id, count in enumerate(counts, 1):
                plays.append(play(play_id, game_id, defense=defense))
                if count is not None:
                    charts.append(chart(play_id, count, game_id))
        report = calculate_rankings(2026, schedule, [], plays, charts)
        self.assertEqual([team(report, name)['blitz']['rank'] for name in 'BCDEF'], [1, 2, 2, 4, None])
        self.assertEqual(team(report, 'E')['blitz']['value'], 0)
        self.assertFalse(team(report, 'E')['blitz']['incomplete'])
        self.assertTrue(team(report, 'D')['blitz']['incomplete'])
        self.assertIsNone(team(report, 'F')['blitz']['value'])

    def test_missing_epa_and_entire_game_are_not_zero(self):
        report = calculate_rankings(2026, [game(), game('g2', week=2)], [],
                                    [play(1, epa='2'), play(2, epa='NA'), play(3, epa='NaN')], [])
        metric = headline(report)
        self.assertEqual(metric['value'], 2)
        self.assertTrue(metric['incomplete'])
        self.assertEqual(metric['coverage'], {'games_used': 1, 'games_expected': 2, 'samples_used': 1, 'samples_expected': 3})
        self.assertIsNone(team(report)['games'][1]['categories']['passing_offense']['headline']['value'])
        self.assertIsNone(headline(report, 'B')['rank'])

    def test_regular_season_completed_games_only_and_teams_with_no_games(self):
        schedule = [game(), game('post', game_type='POST'), game('pre', game_type='PRE'),
                    game('future', home='C', away='D', home_score='', away_score=''), game('old', season='2025')]
        plays = [play(1)] + [play(i, key, epa='100') for i, key in enumerate(['post', 'pre', 'future', 'old'], 2)]
        report = calculate_rankings(2026, schedule, [], plays, [])
        self.assertEqual(report['completed_games'], 1)
        self.assertEqual(headline(report)['value'], 1)
        self.assertEqual(team(report, 'C')['games_played'], 0)
        self.assertIsNone(headline(report, 'C')['rank'])

    def test_supporting_ratios_use_season_totals_and_defense_uses_opponent(self):
        rows = [stats(passing_yards='100', attempts='10', completions='10'),
                stats('g2', passing_yards='90', attempts='30', completions='0', passing_tds='2'),
                stats(team='B', opponent='A', passing_yards='77')]
        report = calculate_rankings(2026, [game(), game('g2', week=2)], rows, [], [])
        support = team(report)['categories']['passing_offense']['supporting']
        self.assertEqual(support['yards_per_game']['value'], 95)
        self.assertEqual(support['yards_per_attempt']['value'], 4.75)
        self.assertEqual(support['completion_percentage']['value'], 25)
        self.assertEqual(support['touchdowns']['value'], 3)
        allowed = team(report)['categories']['passing_defense']['supporting']['yards_per_game']
        self.assertEqual(allowed['value'], 77)
        self.assertTrue(allowed['incomplete'])

    def test_missing_ratio_components_exclude_whole_pair(self):
        rows = [stats(), stats('g2', passing_yards='', attempts='20')]
        report = calculate_rankings(2026, [game(), game('g2', week=2)], rows, [], [])
        value = team(report)['categories']['passing_offense']['supporting']['yards_per_attempt']
        self.assertEqual(value['value'], 10)
        self.assertTrue(value['incomplete'])

    def test_zero_attempts_remain_undefined_and_zero_sacks_are_valid(self):
        report = calculate_rankings(2026, [game()], [stats(attempts='0', completions='0', passing_yards='0', def_sacks='0')], [], [])
        self.assertIsNone(team(report)['categories']['passing_offense']['supporting']['completion_percentage']['value'])
        self.assertEqual(headline(report, category='pass_rush')['value'], 0)
        self.assertEqual(headline(report, category='pass_rush')['rank'], 1)

    def test_sack_context_counts_repeat_opponents_and_includes_head_to_head(self):
        schedule = [game(), game('g2', week=2), game('g3', away='C', week=3), game('g4', home='B', away='C', week=4)]
        rows = [stats(), stats('g2'), stats('g3', opponent='C'),
                stats(team='B', opponent='A', sacks_suffered='0'),
                stats('g2', team='B', opponent='A', sacks_suffered='3'),
                stats('g4', team='B', opponent='C', sacks_suffered='6'),
                stats('g3', team='C', opponent='A', sacks_suffered='8'),
                stats('g4', team='C', opponent='B', sacks_suffered='10')]
        report = calculate_rankings(2026, schedule, rows, [], [])
        category = team(report)['categories']['pass_rush']
        self.assertEqual(category['supporting']['opponent_sacks_allowed_per_game']['value'], 5)
        logs = team(report)['games']
        self.assertEqual([log['categories']['pass_rush']['supporting']['opponent_sacks_allowed_per_game']['value'] for log in logs], [3, 3, 9])
        self.assertEqual(logs[0]['categories']['pass_rush']['opponent_current_rank'], headline(report, 'B', 'pass_protection')['rank'])

    def test_exact_competition_ties_without_display_rounding(self):
        teams = [{'team': str(i), 'categories': {key: {'headline': {'value': value, 'rank': None}} for key in CATEGORIES}}
                 for i, value in enumerate([Fraction(3), Fraction(2), Fraction(2), Fraction(19999, 10000), None])]
        assign_ranks(teams)
        self.assertEqual([t['categories']['passing_offense']['headline']['rank'] for t in teams], [1, 2, 2, 4, None])
        self.assertEqual([t['categories']['passing_defense']['headline']['rank'] for t in teams], [4, 2, 2, 1, None])

    def test_duplicates_and_team_mismatch_are_reported(self):
        cases = [([stats(), stats()], [], []), ([], [play(1), play(1)], []),
                 ([], [], [chart(1, 0), chart(1, 1)]), ([], [play(1, defense='C')], [])]
        for rows, plays, charts in cases:
            with self.assertRaises(SourceError):
                calculate_rankings(2026, [game()], rows, plays, charts)


if __name__ == '__main__':
    unittest.main()
