"""Read-only audit of real report arithmetic against its saved source revisions.

Usage: PYTHONPATH=. python scripts/verify_margin_inputs.py DATABASE API_EVIDENCE OUTPUT
No fixture creation, timestamps rewritten, or provider fetches.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from backend.college_strength import calculate_strength
from backend.elo import APPROVED_CONFIG, CENTER, prepare_elo_history, replay_elo
from backend.margins import stamp
from backend.matchups import TEAM_NAMES
from backend.storage import SnapshotStore


def verify(database, evidence):
    store = SnapshotStore(database)
    sources = {}
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        for key, payload, metadata in connection.execute('SELECT source_key,payload,metadata FROM source_snapshots WHERE payload IS NOT NULL'):
            if key.split(':')[0] in ('schedule', 'elo_history', 'kalshi_teams', 'kalshi_games', 'spreads', 'cfb_schedule', 'cfb_strength', 'cfb_markets', 'cfb_research') or key.startswith('cfb_history:'):
                sources[key] = {**json.loads(metadata), 'payload_sha256': hashlib.sha256(gzip.decompress(payload)).hexdigest()}
    memo, checked, neutral = {}, 0, []
    for report in evidence['reports']:
        for game in report['games']:
            f = game['forecast']
            if not f['available']:
                continue
            sport = 'cfb' if f['experimental'] else 'nfl'
            season, freeze = f['season'], stamp(f['ratings_as_of'])
            for source in f['source_freshness']:
                assert sources[f"{source['name']}:{season}"]['fetched_at'] == source['fetched_at'], 'Inputs changed since report capture; recapture HTTP evidence before verifying.'
            key = sport, season, freeze
            if key not in memo:
                if sport == 'cfb':
                    strength = calculate_strength(store.read(f'cfb_strength:{season}').rows[0], season, now=freeze)
                    memo[key] = {t['id']: t['rating'] for t in strength['teams']}
                else:
                    rows = store.read(f'elo_history:{season}').rows
                    games = prepare_elo_history(rows, end_season=season, as_of=stamp(f['prediction_as_of']))
                    games = [g for g in games if g['home_score'] is not None and stamp(g['kickoff']) < freeze]
                    replay = replay_elo(games, APPROVED_CONFIG, teams=TEAM_NAMES, freeze_dates=True)
                    ratings = replay['ratings']
                    if season not in replay['season_openings']:
                        ratings = {t: CENTER + (r-CENTER)*APPROVED_CONFIG.offseason_retention for t, r in ratings.items()}
                    xy = xx = 0
                    for row in replay['games']:
                        if row['season'] < 2007:
                            continue
                        x = row['home_rating_before'] - row['away_rating_before'] + row['home_advantage']
                        xy += x * (row['home_score'] - row['away_score'])
                        xx += x*x
                    memo[key] = ratings, xy/xx
            if sport == 'cfb':
                ratings = memo[key]
                expected = ratings[f['home_team_id']] - ratings[f['away_team_id']] + (0 if f['neutral'] else 2)
            else:
                ratings, beta = memo[key]
                assert abs(beta-f['calibration']['points_per_elo']) < 1e-12
                expected = beta * (ratings[f['home_team_id']] - ratings[f['away_team_id']] + (0 if f['neutral'] else APPROVED_CONFIG.home_advantage))
            assert abs(expected-f['home_margin']) < 1e-9, game['game_id']
            checked += 1
            if f['neutral']:
                neutral.append({'sport': sport, 'game_id': game['game_id'], 'venue': game['venue'], 'home_margin': expected, 'home_advantage': 0})
    return {'verified_at': datetime.now(timezone.utc).isoformat(), 'checked_forecasts': checked,
            'neutral_games': neutral, 'sources': sources}


if __name__ == '__main__':
    database, evidence, output = map(Path, sys.argv[1:])
    result = verify(database, json.loads(evidence.read_text()))
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'sources'}, indent=2))
