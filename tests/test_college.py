import copy
import csv
import gzip
import io
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from backend.catalog import CFB_SOURCES, SOURCES, RefreshService
from backend.college import college_matchups, college_rankings
from backend.sources.college import DATASETS, REQUIRED, load_college, validate_bundle
from backend.sources.common import Resource, SourceData, SourceError
from backend.storage import SnapshotStore

NOW = datetime(2026, 10, 24, 16, tzinfo=timezone.utc)


def game(gid, home='1', away='2', date='2026-10-10T19:00:00Z', completed='true', week='6', fcs=False):
    return dict(game_id=gid, season='2026', week=week, season_type='regular', start_date=date,
                start_time_tbd='false', completed=completed, neutral_site='false',
                home_id=home, away_id=away, home_team='Team ' + home, away_team='Team ' + away,
                home_division='fbs', away_division='fcs' if fcs else 'fbs',
                fbs_participant='true', fbs_game='false' if fcs else 'true')


def bundle():
    schedule = [game('100'), game('101', away='3', date='2026-10-17T19:00:00Z'),
                game('102', away='9', date='2026-10-03T19:00:00Z', fcs=True),
                game('103', date='2026-10-24T19:30:00Z', completed='false', week='8')]
    result = {'schedule': schedule, **{key: [] for key in DATASETS if key != 'schedule'}}
    for g in schedule[:3]:
        for tid in [g['home_id'], g['away_id']]:
            for key, (_, _, team_key) in DATASETS.items():
                if key == 'schedule':
                    continue
                row = {k: '0' for k in REQUIRED[key]}
                row.update(game_id=g['game_id'], season='2026', **{team_key: tid})
                if key == 'adv_team':
                    row.update(EPA_passing_per_play='0.1', EPA_rushing_per_play='0.1')
                    if g['game_id'] == '102' and tid == '1': row['EPA_rushing_per_play'] = '0.9'
                if key == 'adv_defensive': row['sacks'] = '2'
                if key == 'team_box':
                    row.update(netPassingYards='200', completionAttempts='10/20', rushingYards='100', rushingAttempts='20', interceptions='1')
                result[key].append(row)
    return result


def fetcher(data):
    def fetch(url):
        key = next(k for k, (_, name, _) in DATASETS.items() if url.endswith(name.format(season=2026)))
        rows = data[key]
        output = io.StringIO()
        headers = sorted(REQUIRED[key] | {'game_id', 'season', DATASETS[key][2]})
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
        raw = output.getvalue().encode()
        return Resource(gzip.compress(raw) if key == 'schedule' else raw, url, NOW.isoformat())
    return fetch


class CollegeRankingTests(unittest.TestCase):
    def test_exact_ties_weight_games_and_suppress_fcs_teams(self):
        data = bundle()
        for include_fcs in (False, True):
            report = college_rankings(data, 2026, include_fcs=include_fcs, now=NOW)
            self.assertEqual(set(report['teams']), {'1', '2', '3'})
            own = report['teams']['1']['categories']['rushing_offense']
            self.assertEqual(own['games_used'], 3 if include_fcs else 2)
            self.assertAlmostEqual(own['value'], 1.1 / 3 if include_fcs else .1)
            self.assertEqual(report['teams']['2']['categories']['rushing_offense']['rank'], 2 if include_fcs else 1)
            self.assertEqual(report['teams']['3']['categories']['rushing_offense']['rank'], 2 if include_fcs else 1)
            if include_fcs:
                fcs = next(g for g in own['games'] if g['opponent_id'] == '9')
                self.assertIsNone(fcs['opponent_current_rank'])
                self.assertIsNone(fcs['opponent_current_metric'])
                self.assertEqual(own['schedule_context']['opponents_used'], 2)

    def test_missing_value_excluded_and_coverage_flagged(self):
        data = bundle()
        data['adv_team'][0]['EPA_passing_per_play'] = ''
        own = college_rankings(data, 2026, now=NOW)['teams']['1']['categories']['passing_offense']
        self.assertEqual(own['games_used'], 1)
        self.assertEqual(own['games_expected'], 2)
        self.assertEqual(own['missing_game_ids'], ['100'])
        self.assertAlmostEqual(own['value'], .1)

    def test_defense_uses_opponent_performance_and_repeated_opponents(self):
        data = bundle()
        data['adv_team'][1]['EPA_passing_per_play'] = '-0.3'
        report = college_rankings(data, 2026, now=NOW)
        defense = report['teams']['1']['categories']['passing_defense']
        self.assertAlmostEqual(defense['value'], -.1)
        self.assertEqual(defense['rank'], 1)
        data['schedule'][1]['away_id'] = '2'
        data['schedule'][1]['away_team'] = 'Team 2'
        for name, (_, _, key) in DATASETS.items():
            if name != 'schedule':
                for row in data[name]:
                    if row[key] == '3': row[key] = '2'
        own = college_rankings(data, 2026, now=NOW)['teams']['1']['categories']['passing_offense']
        self.assertEqual(own['schedule_context']['opponents_used'], 2)

    def test_pooled_support_ratios_and_no_empty_zero_totals(self):
        data = bundle()
        data['team_box'][2].update(netPassingYards='100', completionAttempts='5/10')
        own = college_rankings(data, 2026, now=NOW)['teams']['1']['categories']['passing_offense']
        self.assertEqual(own['supporting']['yards_per_attempt']['value'], 10)
        self.assertIsNone(own['supporting']['touchdowns']['value'])
        empty = college_rankings(data, 2026, now=datetime(2026, 1, 1, tzinfo=timezone.utc))['teams']['1']['categories']['passing_offense']
        self.assertIsNone(empty['value'])
        self.assertIsNone(empty['supporting']['interceptions']['value'])

    def test_matchup_filter_keeps_league_ranks_and_no_unknown_game(self):
        full = college_rankings(bundle(), 2026, now=NOW)
        pair = college_rankings(bundle(), 2026, game_id='103', now=NOW)
        self.assertEqual(set(pair['teams']), {'1', '2'})
        self.assertEqual(pair['teams']['1'], full['teams']['1'])
        with self.assertRaises(SourceError): college_rankings(bundle(), 2026, game_id='999', now=NOW)

    def test_upcoming_regular_games_timezone_tbd_and_missing_finals(self):
        data = bundle()
        data['schedule'] += [game('104', date='2026-10-24T11:00:00-05:00', completed='false', week='8'),
                             game('105', date='2026-10-24T04:00:00Z', completed='false', week='8')]
        data['schedule'][-1]['start_time_tbd'] = 'true'
        report = college_matchups(data, 2026, now=NOW)
        self.assertEqual(report['week'], 8)
        self.assertEqual({g['game_id'] for g in report['games']}, {'103', '105'})
        self.assertTrue(next(g for g in report['games'] if g['game_id'] == '105')['time_tbd'])
        self.assertEqual(college_matchups(data, 2026, week=6, now=NOW)['games'], [])


class CollegeSourceTests(unittest.TestCase):
    def test_real_reader_validates_fixture_and_separate_catalog(self):
        result = load_college(2026, fetcher(bundle()))
        self.assertEqual(len(result.context['resources']), 5)
        self.assertEqual(len(result.rows[0]['schedule']), 4)
        self.assertFalse(any(s.name.startswith('cfb_') for s in SOURCES))
        self.assertEqual(CFB_SOURCES[0].key(2026), 'cfb_research:2026')

    def test_rejects_duplicate_wrong_season_unknown_division_and_invalid_numbers(self):
        for mutate in [lambda d: d['schedule'].append(copy.deepcopy(d['schedule'][0])),
                       lambda d: d['adv_team'].append(copy.deepcopy(d['adv_team'][0])),
                       lambda d: d['adv_team'][0].update(season='2025'),
                       lambda d: d['schedule'][0].update(start_date='2026-10-10'),
                       lambda d: d['schedule'][0].update(away_division='unknown'),
                       lambda d: d['adv_team'][0].update(EPA_passing_per_play='Infinity'),
                       lambda d: d['adv_defensive'][0].update(sacks='-1'),
                       lambda d: d['team_box'][0].update(rushingAttempts='-1'),
                       lambda d: d['team_box'][0].update(completionAttempts='20/10'),
                       lambda d: d.update(adv_team=[])]:
            with self.subTest(mutation=mutate):
                data = bundle(); mutate(data)
                with self.assertRaises(SourceError): load_college(2026, fetcher(data))

    def test_partial_table_reports_missing_coverage(self):
        data = bundle(); data['adv_team'].pop()
        self.assertEqual(validate_bundle(data, 2026)['adv_team'], 1)
        self.assertTrue(any('1 completed team-game' in w for w in load_college(2026, fetcher(data)).warnings))

    def test_failed_refresh_retains_previous_college_and_nfl_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SnapshotStore(Path(folder) / 'test.sqlite3'); store.initialize()
            store.save('schedule:2026', SourceData([{'nfl': True}], 'test', NOW.isoformat()))
            good = RefreshService(store, fetcher(bundle()))
            self.assertEqual(good.refresh('cfb_research', 2026)['status'], 'ready')
            previous = store.read('cfb_research:2026').rows
            broken = bundle(); broken['adv_defensive'][0]['sacks'] = 'bad'
            bad = RefreshService(store, fetcher(broken))
            self.assertEqual(bad.refresh('cfb_research', 2026)['status'], 'refresh_failed')
            self.assertEqual(store.read('cfb_research:2026').rows, previous)
            self.assertEqual(store.read('schedule:2026').rows, [{'nfl': True}])
            self.assertIsNone(store.read('cfb_research:2025'))


if __name__ == '__main__':
    unittest.main()
