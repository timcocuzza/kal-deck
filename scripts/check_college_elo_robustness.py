"""Frozen-setting follow-up diagnostics; never searches held-out parameters.

python3 scripts/check_college_elo_robustness.py /tmp/deck-cfb-audit docs/research/cfb-elo
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from compare_college_elo import (read_history, replay, scoring_rows, evaluate, metrics,
                                 paired_interval, write_json, convert, sha256)


def check(cache, output):
    lock = json.loads((output / 'selection-lock.json').read_text())
    protocol = json.loads((output / 'protocol.json').read_text())
    if sha256(output / 'protocol.json') != lock['protocol_sha256']:
        raise ValueError('Protocol differs from frozen selection')
    years = protocol['held_out_seasons']
    all_games, _ = read_history(cache)
    games = [g for g in all_games if g.season >= protocol['warmup_seasons'][0]]
    config = lock['selected']['config']
    original = replay(games, config)
    held = scoring_rows(original, years)
    early_ids = {r['game'].id for r in held if min(r['home_games_before'], r['away_games_before']) < 3}
    variants = {name: replay(games, entry['config']) for name, entry in lock['retention_candidates'].items()}
    variants['without_fcs'] = replay([g for g in games if g.matchup == 'fbs-fbs'], config)
    variants['high_carryover_diagnostic'] = replay(games, {**config, 'retention': 2 / 3})
    comparisons = {}
    for name, logs in variants.items():
        rows = scoring_rows(logs, years)
        comparisons[name] = {'variant_minus_selected': paired_interval(rows, held),
                             'early_season_on_identical_game_ids': metrics([r for r in rows if r['game'].id in early_ids])}
    corrections = json.loads((output / 'venue-corrections.json').read_text())['corrections']
    corrected = {g.id: g for g in games}
    for item in corrections:
        game = corrected[item['game_id']]
        if (game.season, game.home, game.away, game.home_score, game.away_score, game.day, game.neutral) != (
                item['season'], item['home_id'], item['away_id'], item['home_score'], item['away_score'], item['date'], item['bulk_neutral']):
            raise ValueError('Correction identity or original value no longer matches')
        corrected[game.id] = replace(game, neutral=item['verified_neutral'])
    corrected_games = [corrected[g.id] for g in games]
    venue_results = {}
    for name in ('selected', 'linear', 'win_elo', 'nfl_margin'):
        entry = lock[name]
        before = convert(replay(games, entry['config']), entry['conversion'])
        after = convert(replay(corrected_games, entry['config']), entry['conversion'])
        before_held, after_held = scoring_rows(before, years), scoring_rows(after, years)
        venue_results[name] = {'metrics': evaluate(after, years),
                              'mae_change': metrics(after_held)['mae'] - metrics(before_held)['mae'],
                              'max_held_out_benchmark_change': max(abs(a['benchmark'] - b['benchmark']) for a, b in zip(after_held, before_held))}
    write_json(output / 'robustness.json', {'status': 'Frozen settings; diagnostic comparisons do not select a replacement',
               'selection_lock_sha256': sha256(output / 'selection-lock.json'),
               'retention_and_fcs_comparisons': comparisons,
               'venue_correction': {'corrections_sha256': sha256(output / 'venue-corrections.json'), 'results': venue_results},
               'notes': ['Early-season sensitivity comparisons use identical game IDs from the full replay.',
                         'Repeated use of this holdout for further tuning would make it development data, not independent validation.',
                         'The stronger-carryover diagnostic is not authorization to change the user preference.']})
    print(json.dumps({'variant_comparisons': {k: v['variant_minus_selected'] for k, v in comparisons.items()},
                      'venue_correction_mae_changes': {k: v['mae_change'] for k, v in venue_results.items()}}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    check(args.cache, args.output)
