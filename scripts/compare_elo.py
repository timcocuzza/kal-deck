"""Offline Elo parameter experiment. Does not set production defaults or touch SQLite.

Run: PYTHONPATH=. .venv/bin/python scripts/compare_elo.py INPUT_CSV OUTPUT_JSON
Only 2002–2025 games are used. 2002–2006 warm up ratings; 2007–2021 select
parameters; 2022–2025 evaluate the selected candidate and predeclared baselines.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
import math
from pathlib import Path

from backend.elo import EloConfig, prepare_elo_history, replay_elo


def score(games):
    if not games:
        raise ValueError('Cannot evaluate an empty game set.')
    loss, squared = 0.0, 0.0
    bins = [[] for _ in range(10)]
    for game in games:
        probability, actual = game['home_expected_score'], game['home_result']
        p = min(1 - 1e-15, max(1e-15, probability))
        loss -= actual * math.log(p) + (1 - actual) * math.log1p(-p)
        squared += (probability - actual) ** 2
        bins[min(9, int(probability * 10))].append((probability, actual))
    return {
        'games': len(games), 'ties': sum(game['home_result'] == 0.5 for game in games),
        'cross_entropy': loss / len(games), 'mean_squared_expected_score_error': squared / len(games),
        'calibration': [{'range': [i / 10, (i + 1) / 10], 'games': len(bucket),
                         'mean_forecast': sum(p for p, _ in bucket) / len(bucket),
                         'mean_result_with_half_credit_for_ties': sum(y for _, y in bucket) / len(bucket)}
                        for i, bucket in enumerate(bins) if bucket],
    }


def compare(rows):
    games = prepare_elo_history(rows, 2002, 2025)
    candidates = []
    baseline = EloConfig(20, 65, 2 / 3)
    for k, home, retention in product((10, 15, 20, 25, 30, 40), (0, 25, 50, 65, 80), (0.5, 2 / 3, 0.8, 1.0)):
        config = EloConfig(k, home, retention)
        replay = replay_elo(games, config)
        calibration = score([game for game in replay['games'] if 2007 <= game['season'] <= 2021])
        candidates.append({'config': replay['config'], 'calibration': calibration})
    # No held-out outcomes enter candidate selection or tie-breaking.
    candidates.sort(key=lambda item: (item['calibration']['cross_entropy'], item['config']['k'],
                                      item['config']['home_advantage'], item['config']['offseason_retention']))
    chosen = EloConfig(**candidates[0]['config'])
    evaluation = []
    for name, config in (('published_parameter_baseline', baseline), ('selected_on_2007_2021', chosen)):
        replay = replay_elo(games, config)
        validation = [game for game in replay['games'] if 2022 <= game['season'] <= 2025]
        evaluation.append({'name': name, 'config': replay['config'], 'validation': score(validation),
                           'validation_by_season': {str(year): score([game for game in validation if game['season'] == year])
                                                    for year in range(2022, 2026)}})
    baseline_replay = replay_elo(games, baseline)['games']
    training_home = [game for game in baseline_replay if 2007 <= game['season'] <= 2021 and not game['neutral']]
    home_only = sum(game['home_result'] for game in training_home) / len(training_home)
    held_out = [game for game in baseline_replay if 2022 <= game['season'] <= 2025]
    for name, probability in (('always_50_percent', 0.5), ('historical_home_advantage_only', home_only)):
        predictions = [{**game, 'home_expected_score': 0.5 if game['neutral'] else probability} for game in held_out]
        evaluation.append({'name': name, 'home_expected_score': probability, 'validation': score(predictions)})
    return {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'Offline comparison artifact; this script does not change production settings.',
        'history_sha256': hashlib.sha256(json.dumps(games, sort_keys=True).encode()).hexdigest(),
        'history_games': len(games), 'experiment_candidates': len(candidates),
        'protocol': {'initial_rating': 1500, 'elo_scale': 400, 'warmup_seasons': [2002, 2006],
                     'parameter_selection_seasons': [2007, 2021], 'held_out_seasons': [2022, 2025],
                     'current_season_used_for_selection': False, 'phases': ['REG', 'WC', 'DIV', 'CON', 'SB'],
                     'margin': 'log(absolute margin + 1) * 2.2 / (2.2 + winner adjusted Elo difference * 0.001); ties use 2.2 * log(2)',
                     'offseason': '1500 + retention * (previous rating - 1500)',
                     'neutral_sites': 'No home advantage',
                     'outcome': 'Win=1, tie=0.5, loss=0. The model estimates expected score, not a separate three-outcome distribution.',
                     'selection_metric': 'Mean cross entropy against 1/0.5/0 outcomes; lower is better. This is not a win/tie/loss likelihood.',
                     'notes': ['Forecast each game before applying its result.', 'Validation ratings learn from earlier validation results chronologically, with frozen settings.',
                               'Only the calibration-selected candidate and predeclared baselines are scored on held-out seasons.',
                               'Published parameter baseline uses our approved 1500 initialization and league center, not original historical initial ratings.']},
        'calibration_top_10': candidates[:10], 'held_out_comparison': evaluation,
        'reference': 'https://github.com/fivethirtyeight/nfl-elo-game/blob/master/forecast.py',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_csv', type=Path)
    parser.add_argument('output_json', type=Path)
    args = parser.parse_args()
    with args.input_csv.open() as source:
        result = compare(list(csv.DictReader(source)))
    args.output_json.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'candidates': result['experiment_candidates'], 'historical_games': result['history_games'],
                      'selected_candidate': result['calibration_top_10'][0]['config'],
                      'validation': [{key: value for key, value in row.items() if key != 'validation_by_season'}
                                     for row in result['held_out_comparison']]}, indent=2))
