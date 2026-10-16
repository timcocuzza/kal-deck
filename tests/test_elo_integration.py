from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend import app as api
from backend.catalog import RefreshService
from backend.elo import APPROVED_CONFIG, calculate_elo
from backend.matchups import TEAM_NAMES
from backend.sources.common import Resource, SourceError
from backend.storage import SnapshotStore


NOW = datetime(2003, 9, 2, tzinfo=timezone.utc)


def season_rows(year, *, unscored=False):
    teams = sorted(TEAM_NAMES)
    return [{'game_id': f'{year}-{i}', 'season': str(year), 'week': '1', 'game_type': 'REG',
             'gameday': f'{year}-09-01', 'gametime': '13:00', 'location': 'Home',
             'home_team': teams[i], 'away_team': teams[i + 16],
             'home_score': '' if unscored else '20', 'away_score': '' if unscored else '10'}
            for i in range(16)]


def fetch_rows(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return lambda url: Resource(output.getvalue().encode(), url, NOW.isoformat())


class EloIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.rows = season_rows(2002) + season_rows(2003)

    def test_selected_configuration_and_current_season_logs(self):
        result = calculate_elo(2003, self.rows, now=NOW)
        self.assertEqual(result['config'], {'k': 20, 'home_advantage': 50, 'offseason_retention': 2 / 3})
        self.assertEqual(result['replayed_games'], 32)
        self.assertEqual(len(result['teams']), 32)
        self.assertEqual(len(result['matchups']), 16)
        self.assertEqual({team['rank'] for team in result['teams']}, {1, 17})
        self.assertAlmostEqual(result['league']['mean'], 1500)
        self.assertTrue(all(len(team['games']) == 1 for team in result['teams']))
        self.assertTrue(all(game['basis'] == 'pregame_ratings' for game in result['matchups']))

    def test_before_first_game_regresses_once_and_lists_pending_scores(self):
        previous = calculate_elo(2002, self.rows, now=NOW)
        rows = season_rows(2002) + season_rows(2003, unscored=True)
        result = calculate_elo(2003, rows, now=NOW)
        self.assertEqual(result['replayed_games'], 16)
        self.assertEqual(len(result['awaiting_score_game_ids']), 16)
        for old, new in zip(previous['teams'], result['teams']):
            self.assertAlmostEqual(new['rating'], 1500 + (old['rating'] - 1500) * APPROVED_CONFIG.offseason_retention)
            self.assertEqual(new['rating'], new['season_start_rating'])
            self.assertEqual(new['season_change'], 0)
            self.assertIsNone(new['last_change'])
        self.assertEqual(result, calculate_elo(2003, rows, now=NOW))

    def test_future_games_do_not_update_ratings_or_invent_results(self):
        rows = season_rows(2002) + season_rows(2003, unscored=True)
        for row in rows[16:]:
            row['gameday'] = '2003-09-10'
        result = calculate_elo(2003, rows, now=NOW)
        self.assertEqual(result['awaiting_score_game_ids'], [])
        for game in result['matchups']:
            self.assertEqual(game['status'], 'upcoming')
            self.assertIsNone(game['home_score'])
            self.assertNotIn('home_change', game)
            self.assertAlmostEqual(game['home_expected_score'] + game['away_expected_score'], 1)
        rows[16]['home_score'], rows[16]['away_score'] = '20', '10'
        with self.assertRaisesRegex(SourceError, 'before kickoff'):
            calculate_elo(2003, rows, now=NOW)

    def test_initial_season_seeds_all_franchises_before_their_first_results(self):
        rows = season_rows(2002, unscored=True)
        rows[0].update(home_score='20', away_score='10')
        result = calculate_elo(2002, rows, now=NOW)
        self.assertEqual(len(result['teams']), 32)
        self.assertEqual(sum(team['games_played'] for team in result['teams']), 2)
        self.assertEqual(sum(team['rating'] == 1500 for team in result['teams']), 30)
        self.assertEqual(len(result['matchups']), 16)

    def test_correction_replays_once_and_cannot_change_its_own_pregame_forecast(self):
        before = calculate_elo(2003, self.rows, now=NOW)
        self.rows[16]['home_score'] = '0'
        after = calculate_elo(2003, self.rows, now=NOW)
        old, new = before['matchups'][0], after['matchups'][0]
        self.assertEqual(old['home_expected_score'], new['home_expected_score'])
        self.assertNotEqual(old['home_rating_after'], new['home_rating_after'])
        self.assertEqual(after['replayed_games'], before['replayed_games'])
        self.assertEqual(after, calculate_elo(2003, self.rows, now=NOW))

    def test_bad_history_scores_or_franchises_fail_closed(self):
        for index, changes in [(0, {'home_score': '', 'away_score': ''}),
                               (16, {'home_score': ''}), (16, {'home_score': 'NaN'}),
                               (16, {'location': ''}), (16, {'home_team': 'FAKE'})]:
            rows = deepcopy(self.rows)
            rows[index].update(changes)
            with self.subTest(changes=changes), self.assertRaises(SourceError):
                calculate_elo(2003, rows, now=NOW)

    def test_postseason_neutral_games_count_and_preseason_does_not(self):
        playoff = {**self.rows[-1], 'game_id': 'playoff', 'game_type': 'SB',
                   'gameday': '2004-02-01', 'location': 'Neutral'}
        preseason = {**playoff, 'game_id': 'pre', 'game_type': 'PRE'}
        result = calculate_elo(2003, self.rows + [playoff, preseason],
                               now=datetime(2004, 3, 1, tzinfo=timezone.utc))
        self.assertEqual(result['replayed_games'], 33)
        self.assertEqual(result['matchups'][-1]['home_advantage'], 0)
        self.assertEqual(result['matchups'][-1]['phase'], 'SB')

    def test_cache_failure_retention_api_provenance_and_season_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / 'test.sqlite3')
            store.initialize()
            service = RefreshService(store, fetch_rows(self.rows))
            with patch.object(api, 'store', store), patch.object(api, 'refresh_service', service):
                self.assertFalse(api.elo(2003)['available'])
                self.assertEqual(service.refresh('elo_history', 2003)['status'], 'ready')
                original = api.elo(2003)
                self.assertTrue(original['available'])
                self.assertEqual(original['sources'][0]['fetched_at'], NOW.isoformat())
                self.assertFalse(api.elo(2004)['available'])
                broken = deepcopy(self.rows)
                broken[0]['home_score'] = ''
                service.fetch = fetch_rows(broken)
                self.assertEqual(service.refresh('elo_history', 2003)['status'], 'refresh_failed')
                retained = api.elo(2003)
                self.assertEqual(original['teams'], retained['teams'])
                self.assertEqual(retained['sources'][0]['status'], 'refresh_failed')
                self.assertEqual(retained['sources'][0]['fetched_at'], NOW.isoformat())
                # A malformed legacy/on-disk snapshot cannot produce a partial rating.
                saved = store.read('elo_history:2003')
                saved.rows = broken
                store.save('elo_history:2003', saved)
                with self.assertRaises(HTTPException) as raised:
                    api.elo(2003)
                self.assertEqual(raised.exception.status_code, 422)


if __name__ == '__main__':
    unittest.main()
