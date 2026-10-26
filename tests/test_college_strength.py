"""Rating invariants, result coverage, and evidence presented to FBS users."""
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime, timezone
import csv
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from backend.catalog import RefreshService
from backend.college_rating import CONFIG, Game, replay
from backend.college_strength import calculate_strength
from backend.sources.college_history import normalize, load_history, live_schedule
from backend.sources.college_schedule import parse_week
from backend.sources.common import Resource, SourceData, SourceError
from backend.storage import SnapshotStore
from scripts.compare_college_elo import replay as reference_replay

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def result(gid='1', year=2026, day='09-01', home='1', away='2', divisions=('fbs', 'fbs'), score=(35, 7)):
    return dict(game_id=gid, season=str(year), week='1', season_type='regular',
                start_date=f'{year}-{day}T18:00:00Z', start_time_tbd='false',
                completed='true', neutral_site='false', status='STATUS_FINAL',
                home_id=home, away_id=away, home_team='Team ' + home, away_team='Team ' + away,
                home_division=divisions[0], away_division=divisions[1],
                home_points=str(score[0]), away_points=str(score[1]),
                fbs_participant=str('fbs' in divisions).lower(), fbs_game=str(set(divisions) == {'fbs'}).lower())


def bundle(*rows):
    seasons = sorted({int(r['season']) for r in rows})
    games, rosters = [], {}
    for year in seasons:
        normalized, roster = normalize([r for r in rows if r['season'] == str(year)], year, now=NOW)
        games.extend(normalized); rosters[str(year)] = roster
    return dict(games=games, rosters=rosters)


def page(row, phase=2):
    status = {'type': {'name': row['status'], 'state': 'post' if row['completed'] == 'true' else 'pre',
                       'completed': row['completed'] == 'true'}}
    competition = dict(id=row['game_id'], date=row['start_date'], timeValid=True, dateValid=True,
                       neutralSite=row['neutral_site'] == 'true', status=status,
                       competitors=[{'id': row[s + '_id'], 'homeAway': s, 'score': row[s + '_points'],
                                     'team': {'id': row[s + '_id'], 'displayName': row[s + '_team']}}
                                    for s in ('home', 'away')])
    event = dict(id=row['game_id'], date=row['start_date'], season={'year': int(row['season']), 'type': phase},
                 week={'number': int(row['week'])}, status=deepcopy(status), competitions=[competition])
    return dict(season=event['season'], week=event['week'], events=[event])


class CollegeStrengthTests(unittest.TestCase):
    def test_production_matches_frozen_reference_through_spring_and_transition(self):
        rows = [result(year=2020), result('2', 2020, '09-08', away='3', divisions=('fbs', 'fcs')),
                {**result('3', 2020, '09-15', away='3', divisions=('fbs', 'fcs')),
                 'start_date': '2021-03-01T18:00:00Z', 'season_type': 'spring_regular'},
                result('4', 2021, away='3'), result('5', 2023, away='4')]
        keys = {f.name for f in fields(Game)}
        games = [Game(**{k: g[k] for k in keys}) for g in bundle(*rows)['games']]
        self.assertEqual(replay(games, CONFIG), reference_replay(games, CONFIG))
        self.assertEqual(replay(games, CONFIG), replay(games, CONFIG, reverse_day=True))
        changed = [*games[:-1], replace(games[-1], home_score=0, away_score=99)]
        self.assertEqual(replay(games, CONFIG)[:-1], replay(changed, CONFIG)[:-1])

    def test_evidence_keeps_wins_when_strength_falls_and_hides_fcs_ratings(self):
        rows = [result(str(i), day=f'09-{i:02}', score=(70, 0)) for i in range(1, 6)]
        rows += [result('6', day='09-06', score=(21, 20)),
                 result('7', day='09-07', away='3', divisions=('fbs', 'fcs'))]
        report = calculate_strength(bundle(*rows), 2026, now=NOW)
        self.assertEqual({t['id'] for t in report['teams']}, {'1', '2'})
        team = next(t for t in report['teams'] if t['id'] == '1')
        self.assertEqual(team['record']['wins'], 7)
        self.assertEqual(team['fbs_record']['wins'], 6)
        self.assertEqual(team['vs_current_top25']['wins'], 6)
        self.assertLess(team['games'][5]['change'], 0)
        fcs = team['games'][-1]
        for key in ('opponent_pregame_rating', 'opponent_pregame_rank', 'opponent_current_rating', 'opponent_current_rank', 'benchmark'):
            self.assertIsNone(fcs[key])
        self.assertEqual(fcs['result'], 'W')
        self.assertTrue(all(g['opponent_is_fbs'] for g in team['strongest_wins']))
        self.assertAlmostEqual(team['season_change'], sum(g['change'] for g in team['games']))

    def test_schedule_context_uses_venue_and_freezes_pregame_values(self):
        first = result(score=(35, 7))
        a = calculate_strength(bundle(first), 2026, now=NOW)
        teams = {t['id']: t for t in a['teams']}
        self.assertEqual(teams['1']['schedule_faced'], -2)
        self.assertEqual(teams['2']['schedule_faced'], 2)
        self.assertEqual(teams['2']['schedule_faced_rank'], 1)
        b = calculate_strength(bundle(first, result('2', day='09-08', home='2', away='3', score=(70, 0))), 2026, now=NOW)
        later = next(t for t in b['teams'] if t['id'] == '1')
        self.assertEqual(teams['1']['schedule_faced'], later['schedule_faced'])
        self.assertNotEqual(teams['1']['opponents_now'], later['opponents_now'])
        self.assertEqual(teams['1']['games'][0]['opponent_pregame_rating'], later['games'][0]['opponent_pregame_rating'])

    def test_pending_canceled_and_future_games_never_change_ratings(self):
        rows = [result(), {**result('2', day='10-01'), 'completed': 'false', 'status': 'STATUS_IN_PROGRESS'},
                {**result('3', day='10-08'), 'completed': 'false', 'status': 'STATUS_CANCELED'},
                {**result('4', day='10-15'), 'completed': 'false', 'status': 'STATUS_POSTPONED'},
                {**result('5', day='11-01', away='3'), 'completed': 'false', 'status': 'STATUS_SCHEDULED'}]
        report = calculate_strength(bundle(*rows), 2026, now=NOW)
        self.assertEqual(report['replayed_games'], 1)
        self.assertEqual(report['awaiting_final_count'], 1)
        idle = next(t for t in report['teams'] if t['id'] == '3')
        self.assertIsNone(idle['schedule_faced'])
        self.assertIsNone(idle['schedule_faced_rank'])
        self.assertEqual(idle['games_rated'], 0)
        self.assertTrue(idle['notices'])

    def test_preseason_retention_and_new_program_prior(self):
        data = bundle(result(year=2025), {**result('2', away='3'), 'completed': 'false', 'status': 'STATUS_SCHEDULED'})
        report = calculate_strength(data, 2026, now=NOW)
        teams = {t['id']: t for t in report['teams']}
        self.assertAlmostEqual(teams['1']['rating'], 5.2 * .4)
        self.assertEqual(teams['3']['rating'], 0)


class CollegeHistorySourceTests(unittest.TestCase):
    def test_invalid_results_fail_closed(self):
        for update in ({'home_points': ''}, {'home_points': '-1'}, {'completed': 'TRUE'},
                       {'start_date': '2027-11-01T18:00:00Z'}, {'home_id': '2'},
                       {'status': 'STATUS_SCHEDULED'}, {'neutral_site': ''}):
            with self.subTest(update=update), self.assertRaises(SourceError):
                normalize([{**result(), **update}], 2026, now=NOW)
        with self.assertRaises(SourceError): normalize([result(), result('2')], 2026, now=NOW)
        with self.assertRaises(SourceError): normalize([result(), result()], 2026, now=NOW)

    def test_reviewed_venue_correction_is_identity_guarded(self):
        row = {**result('400795729', 2015, '10-03', '2571', '2449', ('fcs', 'fcs'), (7, 28)), 'neutral_site': 'true'}
        rows = [row, result('8', 2015, '10-04')]
        games, _ = normalize(rows, 2015, now=NOW)
        self.assertFalse(games[0]['neutral']); self.assertTrue(games[0]['venue_corrected'])
        with self.assertRaises(SourceError): normalize([{**row, 'home_points': '8'}, rows[1]], 2015, now=NOW)

    def test_neutral_label_swap_requires_exact_scores_teams_and_date(self):
        original = {**result(), 'neutral_site': 'true'}
        flipped = {**result(home='2', away='1', score=(7, 35)), 'neutral_site': 'true'}
        membership = {'1': 'fbs', '2': 'fbs'}
        parsed = parse_week(page(flipped), 2026, 1, {'1': original}, membership, allow_neutral_swap=True)
        self.assertTrue(parsed[0]['neutral_labels_reversed'])
        for update in ({'neutral_site': 'false'}, {'home_points': '8'}, {'start_date': '2026-09-02T18:00:00Z'}):
            with self.subTest(update=update), self.assertRaises(SourceError):
                parse_week(page({**flipped, **update}), 2026, 1, {'1': original}, membership, allow_neutral_swap=True)
        with self.assertRaises(SourceError): parse_week(page(flipped), 2026, 1, {'1': original}, membership)

    def test_current_feed_merges_both_divisions_and_rejects_missing_finals(self):
        rows = [result(), result('2', home='3', away='4', divisions=('fcs', 'fcs'))]
        pages = [page(r) for r in rows]
        def fetch(url):
            q = parse_qs(urlsplit(url).query)
            data = pages[int(q['groups'][0]) - 80] if q['week'] == ['1'] else {'events': []}
            return Resource(json.dumps(data).encode(), url, NOW.isoformat())
        merged, sources = live_schedule(2026, rows, fetch, NOW)
        self.assertEqual({r['game_id'] for r in merged}, {'1', '2'})
        self.assertEqual(len(sources), 30)
        pages[1] = {'events': []}
        with self.assertRaisesRegex(SourceError, 'omitted'): live_schedule(2026, rows, fetch, NOW)
        pages[1] = page({**rows[1], 'completed': 'false', 'status': 'STATUS_SCHEDULED'})
        with self.assertRaisesRegex(SourceError, 'completed'): live_schedule(2026, rows, fetch, NOW)

    def test_numeric_tba_placeholders_cannot_become_rated_teams(self):
        data = page({**result(home='112351', away='112350'), 'completed': 'false', 'status': 'STATUS_SCHEDULED'})
        for c in data['events'][0]['competitions'][0]['competitors']:
            c['team'].update(displayName='TBA', location='TBA', abbreviation='TBA')
        rows = parse_week(data, 2026, 1, {}, {}, require_fbs=False)
        self.assertEqual(rows[0]['home_division'], 'unknown')
        self.assertFalse(rows[0]['participants_confirmed'])
        self.assertEqual(rows[0]['fbs_participant'], 'false')
        data['events'][0]['status']['type'].update(completed=True, state='post', name='STATUS_FINAL')
        data['events'][0]['competitions'][0]['status'] = deepcopy(data['events'][0]['status'])
        with self.assertRaisesRegex(SourceError, 'unconfirmed'): parse_week(data, 2026, 1, {}, {}, require_fbs=False)

    def test_archive_cache_and_failed_refresh_preserve_saved_rating_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SnapshotStore(Path(folder) / 'test.sqlite3'); store.initialize()
            requests = []
            def fetch(url):
                requests.append(url)
                row = result(year=2014)
                out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=list(row))
                writer.writeheader(); writer.writerow(row)
                return Resource(gzip.compress(out.getvalue().encode()), url, NOW.isoformat())
            data = load_history(2014, fetch, store, now=NOW)
            store.save('cfb_strength:2014', data)
            again = load_history(2014, fetch, store, now=NOW)
            self.assertEqual(data.rows, again.rows); self.assertEqual(len(requests), 1)
            store.save('schedule:2026', SourceData([{'nfl': True}], 'test', NOW.isoformat()))
            with patch('backend.catalog.load_college_history', side_effect=SourceError('Missing finals')):
                status = RefreshService(store, fetch).refresh('cfb_strength', 2014)
            self.assertEqual(status['status'], 'refresh_failed')
            self.assertEqual(store.read('cfb_strength:2014').rows, data.rows)
            self.assertEqual(store.read('schedule:2026').rows, [{'nfl': True}])


if __name__ == '__main__':
    unittest.main()
