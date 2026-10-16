from copy import deepcopy
from fractions import Fraction
import unittest

from backend.position_defense import calculate_position_defense, FIELDS, prop_position_categories, position_rank_context
from backend.props import build_player_log
from backend.sources.common import SourceError


def game(gid='g1', home='A', away='B', week=1, **extra):
    return {'game_id': gid, 'season': '2026', 'game_type': 'REG', 'week': str(week),
            'gameday': f'2026-09-{week:02}', 'home_team': home, 'away_team': away,
            'home_score': '10', 'away_score': '7', **extra}


def player(pid='rb', position='RB', team='A', opponent='B', gid='g1', week=1, **extra):
    return {'game_id': gid, 'season': '2026', 'season_type': 'REG', 'week': str(week),
            'team': team, 'opponent_team': opponent, 'player_id': pid, 'position': position,
            'player_display_name': pid, **dict.fromkeys(FIELDS, '0'), **extra}


def team_totals(players):
    grouped = {}
    for row in players:
        key = row['game_id'], row['team']
        total = grouped.setdefault(key, {k: row[k] for k in ('game_id', 'season', 'season_type', 'week', 'team', 'opponent_team')})
        for field in FIELDS:
            total[field] = str(Fraction(total.get(field, '0')) + Fraction(row[field]))
    return list(grouped.values())


def play(pid, yards, play_id, **extra):
    return {'game_id': 'g1', 'season': '2026', 'season_type': 'REG', 'play_id': str(play_id),
            'posteam': 'A', 'defteam': 'B', 'rusher_player_id': pid, 'rushing_yards': str(yards),
            'play_type': 'run', 'rush_attempt': '1', 'qb_scramble': '0', 'qb_kneel': '0',
            'two_point_attempt': '0', **extra}


def report(players, schedule=None, totals=None, plays=None):
    return calculate_position_defense(2026, schedule or [game()], players,
                                      team_totals(players) if totals is None else totals, plays or [])


def team(result, code='B'):
    return next(t for t in result['teams'] if t['team'] == code)


def category(result, key='rb_receiving', code='B'):
    return team(result, code)['categories'][key]


class PositionDefenseTests(unittest.TestCase):
    def test_groups_are_aggregated_against_defense_and_fullbacks_included(self):
        rows = [player(receiving_yards='20', targets='3', receptions='2'),
                player('fb', 'FB', receiving_yards='10', targets='1', receptions='1'),
                player('wr', 'WR', receiving_yards='70', targets='4', receptions='3'),
                player('te', 'TE', receiving_yards='15', targets='2', receptions='1'),
                player('other', 'RB', 'B', 'A')]
        r = report(rows)
        self.assertEqual(category(r)['headline']['value'], 30)
        self.assertEqual(category(r, 'wr_receiving')['headline']['value'], 70)
        self.assertEqual(category(r, 'te_receiving')['headline']['value'], 15)
        self.assertEqual(category(r)['supporting']['targets_per_game']['value'], 4)
        self.assertEqual(category(r)['supporting']['yards_per_target']['value'], 7.5)
        self.assertEqual(category(r, code='A')['headline']['rank'], 1)

    def test_equal_game_headlines_pooled_opportunity_ratios_and_season_tds(self):
        rows = [player(rushing_yards='10', carries='1', rushing_tds='1'),
                player(gid='g2', week=2, rushing_yards='30', carries='9', rushing_tds='2')]
        r = report(rows, [game(), game('g2', week=2)])
        c = category(r, 'rb_rushing')
        self.assertEqual(c['headline']['value'], 20)
        self.assertEqual(c['supporting']['yards_per_carry']['value'], 4)
        self.assertEqual(c['supporting']['touchdowns']['value'], 3)
        self.assertEqual(c['supporting']['carries']['value'], 10)

    def test_verified_zero_counts_but_absent_game_is_not_zero(self):
        rows = [player(), player(gid='g2', week=2, receiving_yards='20', targets='1', receptions='1')]
        schedule = [game(), game('g2', week=2), game('g3', week=3)]
        r = report(rows, schedule)
        h = category(r)['headline']
        self.assertEqual(h['value'], 10)
        self.assertEqual(h['coverage']['games_used'], 2)
        self.assertEqual(h['coverage']['games_expected'], 3)
        self.assertTrue(h['incomplete'])
        self.assertIsNone(team(r)['games'][2]['categories']['rb_receiving']['headline']['value'])

    def test_zero_opportunities_has_zero_yards_and_unavailable_efficiency(self):
        c = category(report([player()]))
        self.assertEqual(c['headline']['value'], 0)
        self.assertFalse(c['headline']['incomplete'])
        self.assertIsNone(c['supporting']['yards_per_target']['value'])

    def test_player_total_reconciliation_detects_partial_or_conflicting_downloads(self):
        rows = [player(receiving_yards='20', targets='2', receptions='1'), player('other', 'RB', receiving_yards='10', targets='1', receptions='1')]
        totals = team_totals(rows)
        for changed in ([rows[0]], [rows[0], {**rows[1], 'receiving_yards': '11'}], [rows[0], {**rows[1], 'targets': ''}]):
            with self.subTest(changed=changed):
                c = category(report(changed, totals=totals))
                self.assertIsNone(c['headline']['value'])

    def test_missing_touchdowns_does_not_remove_verified_yards(self):
        rows = [player(receiving_yards='20', targets='2', receptions='1')]
        totals = team_totals(rows)
        rows[0]['receiving_tds'] = ''
        c = category(report(rows, totals=totals))
        self.assertEqual(c['headline']['value'], 20)
        self.assertIsNone(c['supporting']['touchdowns']['value'])

    def test_duplicates_wrong_week_and_wrong_opponent_withhold_game(self):
        rows = [player(receiving_yards='20', targets='2', receptions='1')]
        totals = team_totals(rows)
        for changed in (rows + rows, [{**rows[0], 'week': '2'}], [{**rows[0], 'opponent_team': 'C'}], [{**rows[0], 'player_id': ''}]):
            with self.subTest(changed=changed):
                self.assertIsNone(category(report(changed, totals=totals))['headline']['value'])
        self.assertIsNone(category(report(rows, totals=totals + totals))['headline']['value'])

    def test_unidentified_zero_only_exception_is_reported_and_never_guesses(self):
        rows = [player(), player('', '', player_display_name='')]
        totals = team_totals(rows)
        r = report(rows, totals=totals)
        self.assertEqual(category(r)['headline']['value'], 0)
        self.assertTrue(any('excluded an unidentified row' in warning for warning in r['warnings']))
        # A benign skipped row must never suppress a real reconciliation failure.
        conflicting_totals = deepcopy(totals)
        conflicting_totals[0]['receiving_yards'] = '1'
        conflict = report(rows, totals=conflicting_totals)
        self.assertIsNone(category(conflict)['headline']['value'])
        self.assertTrue(any('cannot be reconciled' in warning for warning in conflict['warnings']))
        for value in ('1', '', None):
            changed = deepcopy(rows)
            changed[1]['rushing_yards'] = value
            self.assertIsNone(category(report(changed, totals=totals))['headline']['value'])

    def test_unknown_position_with_contributions_is_not_silently_discarded(self):
        rows = [player(position='UNKNOWN', receiving_yards='20', targets='2', receptions='1')]
        r = report(rows)
        self.assertIsNone(category(r)['headline']['value'])
        self.assertEqual(category(r, 'rb_rushing')['headline']['value'], 0)

    def test_qb_official_total_includes_scrambles_designed_runs_and_kneels(self):
        rows = [player('qb', 'QB', rushing_yards='19', carries='3')]
        plays = [play('qb', 10, 1), play('qb', 10, 2, qb_scramble='1'), play('qb', -1, 3, qb_kneel='1', play_type='qb_kneel')]
        c = category(report(rows, plays=plays), 'qb_rushing')
        self.assertEqual(c['headline']['value'], 19)
        self.assertEqual([c['supporting'][key + '_yards_per_game']['value'] for key in ('designed', 'scramble', 'kneel')], [10, 10, -1])

    def test_unverified_qb_split_does_not_remove_official_headline(self):
        rows = [player('qb', 'QB', rushing_yards='10', carries='1')]
        for plays in ([], [play('qb', 9, 1)], [play('qb', 10, 1, qb_scramble='')],
                      [play('qb', 10, 1), play('qb', 10, 1)], [play('qb', 10, 1, defteam='C')],
                      [play('qb', 10, 1, lateral_rusher_player_id='qb')]):
            with self.subTest(plays=plays):
                c = category(report(rows, plays=plays), 'qb_rushing')
                self.assertEqual(c['headline']['value'], 10)
                self.assertIsNone(c['supporting']['designed_yards_per_game']['value'])

    def test_qb_split_reconciles_attempts_and_individual_players_not_just_team_yards(self):
        rows = [player('q1', 'QB', rushing_yards='5', carries='1'), player('q2', 'QB', rushing_yards='5', carries='1')]
        for plays in ([play('q1', 10, 1)], [play('q1', 6, 1), play('q2', 4, 2)], [play('q1', 5, 1), play('q1', 0, 2), play('q2', 5, 3)]):
            self.assertIsNone(category(report(rows, plays=plays), 'qb_rushing')['supporting']['scramble_yards_per_game']['value'])

    def test_nullified_and_two_point_plays_are_not_official_rushing(self):
        rows = [player('qb', 'QB', rushing_yards='10', carries='1')]
        plays = [play('qb', 10, 1), play('qb', 100, 2, two_point_attempt='1'), play('qb', 100, 3, play_type='no_play')]
        c = category(report(rows, plays=plays), 'qb_rushing')
        self.assertEqual(c['supporting']['designed_yards_per_game']['value'], 10)

    def test_current_regular_completed_games_only_and_duplicate_schedule_rejected(self):
        rows = [player(), player(gid='future', week=2), player(gid='post', week=3, season_type='POST'), player(gid='old', season='2025')]
        r = report(rows, [game(), game('future', week=2, home_score='', away_score=''), game('post', week=3, game_type='POST'), game('old', season='2025')])
        self.assertEqual(r['completed_games'], 1)
        self.assertEqual(team(r)['games_played'], 1)
        with self.assertRaises(SourceError):
            report(rows, [game(), game()])

    def test_exact_ties_and_equal_team_league_context(self):
        rows = [player('a', team='A', opponent='B'), player('b', team='B', opponent='A'),
                player('c', team='C', opponent='D', gid='g2', receiving_yards='30', targets='2', receptions='1'),
                player('d', team='D', opponent='C', gid='g2', receiving_yards='10', targets='2', receptions='1')]
        r = report(rows, [game(), game('g2', home='C', away='D')])
        self.assertEqual([category(r, code=code)['headline']['rank'] for code in 'ABCD'], [1, 1, 3, 4])
        self.assertEqual(r['league']['rb_receiving']['mean'], 10)
        self.assertEqual(r['league']['rb_receiving']['median'], 5)

    def test_position_is_taken_from_each_game_and_combined_ranks_stay_separate(self):
        rows = [player('same', 'RB', receiving_yards='10', targets='1', receptions='1'),
                player('same', 'WR', gid='g2', week=2, receiving_yards='20', targets='1', receptions='1')]
        schedule = [game(), game('g2', week=2)]
        r = report(rows, schedule)
        self.assertEqual(category(r)['headline']['value'], 5)
        self.assertEqual(category(r, 'wr_receiving')['headline']['value'], 10)
        self.assertEqual(prop_position_categories('rushing_receiving_yards', 'FB'), ['rb_receiving', 'rb_rushing'])
        self.assertEqual(prop_position_categories('passing_yards', 'QB'), [])
        self.assertEqual(prop_position_categories('rushing_yards', 'WR'), [])
        log = build_player_log(2026, 'same', 'receiving_yards', schedule, rows, [], r['teams'])
        self.assertEqual([row['opponent_ranks'][-1]['category'] for row in log['games']], ['wr_receiving', 'rb_receiving'])
        self.assertEqual(log['games'][0]['opponent_ranks'][0]['category'], 'passing_defense')
        self.assertEqual(len(position_rank_context(r['teams'], 'B', 'rushing_receiving_yards', 'RB')), 2)


if __name__ == '__main__':
    unittest.main()
