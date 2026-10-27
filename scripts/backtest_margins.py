"""Reproducible, offline rolling margin audit; never changes production settings.

PYTHONPATH=. .venv/bin/python scripts/backtest_margins.py /tmp/deck-margin-data docs/research/margins
Inputs: nfl-games.csv (2002–2025), cfb_schedules_{2014..2025}.csv.gz.
Optional --lines PATH accepts timestamped historical lines; see docs/margin-forecasts.md.
"""
import argparse
from collections import Counter
from dataclasses import fields
from datetime import datetime, timedelta, timezone
import csv
import gzip
import hashlib
from itertools import groupby
import json
import math
from pathlib import Path

from backend.elo import APPROVED_CONFIG, prepare_elo_history, replay_elo
from backend.college_rating import CONFIG, Game, replay
from backend.sources.college_history import normalize
from backend.margins import rolling_nfl, stamp

PROSPECTIVE_CUTOFF = '2026-10-28T00:00:00+00:00'


def metrics(rows, key):
    errors = [r[key] - r['actual'] for r in rows if r.get(key) is not None]
    return {'games': len(errors), 'mae': sum(abs(e) for e in errors) / len(errors),
            'rmse': math.sqrt(sum(e * e for e in errors) / len(errors)),
            'bias_prediction_minus_actual': sum(errors) / len(errors)} if errors else {'games': 0}


def market_backtest(predictions, lines):
    """Reject unverifiable joins/times/signs; evaluate all models on paired games.

    Blend weight (strength contribution) and optional constant ATS residual are
    selected on 2017–2021 only, using MAE. Zero wins ties; 2022–2025 is development.
    Lines must have been available by the start-of-UTC-day forecast origin.
    """
    index = {(r['sport'], r['game_id']): r for r in predictions}
    accepted, rejected, seen = {}, Counter(), set()
    for line in lines:
        key = (line.get('sport'), line.get('game_id'))
        game = index.get(key)
        try:
            if not game:
                raise ValueError('unmatched_game')
            if (str(game['season']), game['home'], game['away']) != (line.get('season'), line.get('home_id'), line.get('away_id')):
                raise ValueError('identity_or_season_conflict')
            if line.get('line_convention') != 'home_expected_margin' or not line.get('source'):
                raise ValueError('unverified_sign_or_source')
            quote, observed, origin = stamp(line.get('quoted_at')), stamp(line.get('observed_at')), stamp(game['prediction_as_of'])
            if not quote or not observed or quote > observed or observed > origin or quote > origin:
                raise ValueError('timestamp_unavailable_or_future')
            if stamp(line.get('kickoff')) != stamp(game['kickoff']):
                raise ValueError('kickoff_conflict')
            value = float(line['home_line'])
            if not math.isfinite(value) or abs(value) > 100:
                raise ValueError('invalid_line')
            if (key, quote, line['source']) in seen:
                raise ValueError('duplicate_quote')
            seen.add((key, quote, line['source']))
            if key not in accepted or quote > accepted[key][0]:
                accepted[key] = (quote, {**game, 'market': value})
        except (ValueError, KeyError) as error:
            rejected[str(error)] += 1
    report = {}
    for sport in ('nfl', 'cfb'):
        rows = [r for _, r in accepted.values() if r['sport'] == sport and r.get('strength') is not None]
        train = [r for r in rows if 2017 <= r['season'] <= 2021]
        evaluation = [r for r in rows if 2022 <= r['season'] <= 2025]
        entry = {'paired_training_games': len(train), 'paired_evaluation_games': len(evaluation),
                 'eligible_evaluation_games': sum(r['sport'] == sport and 2022 <= r['season'] <= 2025 for r in predictions)}
        if len(train) < 256 or not evaluation:
            entry['unavailable_reason'] = 'Need at least 256 timestamp-verified earlier training games and evaluation coverage.'
        else:
            weights = [0, .25, .5, .75, 1]
            loss = lambda w: sum(abs(w * r['strength'] + (1 - w) * r['market'] - r['actual']) for r in train) / len(train)
            weight = min(weights, key=lambda w: (loss(w), w))
            residual = sorted(r['actual'] - (weight * r['strength'] + (1 - weight) * r['market']) for r in train)
            correction = (residual[(len(residual)-1)//2] + residual[len(residual)//2]) / 2
            # Zero is a permissible correction, and wins any equal training loss.
            err = lambda c: sum(abs(weight * r['strength'] + (1-weight) * r['market'] + c - r['actual']) for r in train)
            correction = min((0, correction), key=lambda c: (err(c), abs(c)))
            for r in evaluation:
                r['blended'] = weight * r['strength'] + (1-weight) * r['market']
                r['ats_residual'] = r['blended'] + correction
            entry.update(strength_weight=weight, residual_correction=correction,
                         development_metrics={k: metrics(evaluation, k) for k in ('market', 'strength', 'blended', 'ats_residual')})
        report[sport] = entry
    return {'input_rows': len(lines), 'joined_games': len(accepted), 'rejected': dict(rejected),
            'forecast_games': len(predictions), 'sports': report,
            'status': 'Development evidence only; optional models are not shipped.'}


def run(cache):
    hashes = {}
    def read(path, compressed=False):
        body = path.read_bytes()
        hashes[path.name] = hashlib.sha256(body).hexdigest()
        return list(csv.DictReader((gzip.decompress(body) if compressed else body).decode('utf-8-sig').splitlines()))
    nfl = prepare_elo_history(read(cache / 'nfl-games.csv'), end_season=2025)
    records, fit = rolling_nfl(replay_elo(nfl, APPROVED_CONFIG, freeze_dates=True)['games'])
    predictions = [dict(sport='nfl', game_id=g['game_id'], season=g['season'], kickoff=g['kickoff'],
                        home=g['home_team'], away=g['away_team'], neutral=g['neutral'],
                        prediction_as_of=g['prediction_as_of'], training_cutoff=g['training_cutoff'],
                        strength=g['home_margin'], home_only=g['home_only'], zero=0,
                        actual=g['home_score']-g['away_score']) for g in records if g['home_margin'] is not None]
    college, keys = [], {f.name for f in fields(Game)}
    for year in range(2014, 2026):
        games, _ = normalize(read(cache / f'cfb_schedules_{year}.csv.gz', True), year,
                             now=datetime(2026, 10, 27, tzinfo=timezone.utc))
        if any(not g['completed'] and not g['canceled'] for g in games):
            raise ValueError(f'Unresolved college results: {year}')
        college.extend(Game(**{k: g[k] for k in keys}) for g in games if g['completed'])
    logs = replay(sorted(college, key=lambda g: (g.season, g.day, g.id)), CONFIG)
    home_sum, home_n, cutoff, waiting, last_played = 0, 0, None, [], {}
    for day, batch in groupby(logs, key=lambda r: r['game'].day):
        batch = list(batch)
        safe_before = stamp(day+'T00:00:00+00:00')-timedelta(hours=24)
        ready = [g for g in waiting if stamp(g.kickoff) < safe_before]
        waiting = [g for g in waiting if stamp(g.kickoff) >= safe_before]
        for g in ready:
            cutoff = g.kickoff
            if g.home_div == g.away_div == 'fbs' and not g.neutral:
                home_sum += g.margin
                home_n += 1
        for r in batch:
            g = r['game']
            if any(t in last_played and stamp(last_played[t]) >= safe_before for t in (g.home, g.away)):
                raise ValueError('College participant has a prior result inside availability embargo.')
            if g.home_div == g.away_div == 'fbs' and g.season >= 2017:
                predictions.append(dict(sport='cfb', game_id=g.id, season=g.season, kickoff=g.kickoff,
                                        home=g.home, away=g.away, neutral=g.neutral,
                                        prediction_as_of=day+'T00:00:00+00:00', training_cutoff=cutoff,
                                        strength=r['benchmark'], home_only=0 if g.neutral else home_sum/home_n if home_n else None,
                                        zero=0, actual=g.margin))
        for r in batch:
            g = r['game']
            waiting.append(g)
            last_played[g.home] = last_played[g.away] = g.kickoff
    report = {'source_sha256': hashes, 'nfl_final_fit': fit.metadata(),
              'prospective_cutoff': PROSPECTIVE_CUTOFF,
              'protocol': 'Daily frozen predictions, a 24-hour result embargo, and expanding past-only NFL OLS. College CONFIG unchanged. 2022–2025 already inspected: development evidence, not untouched validation.',
              'results': {}}
    for sport in ('nfl', 'cfb'):
        rows = [r for r in predictions if r['sport'] == sport and 2022 <= r['season'] <= 2025]
        report['results'][sport] = {'development_2022_2025': {k: metrics(rows, k) for k in ('strength', 'home_only', 'zero')},
                                    'by_season': {str(y): {k: metrics([r for r in rows if r['season'] == y], k) for k in ('strength', 'home_only', 'zero')} for y in range(2022, 2026)}}
    return report, predictions


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--lines', type=Path)
    args = parser.parse_args()
    report, predictions = run(args.cache)
    lines = list(csv.DictReader(args.lines.open())) if args.lines else []
    report['market_comparison'] = market_backtest(predictions, lines)
    if args.lines:
        report['source_sha256']['historical_lines'] = hashlib.sha256(args.lines.read_bytes()).hexdigest()
    else:
        report['market_comparison']['blocker'] = 'No timestamp-verified historical line file supplied. Untimestamped/closing lines cannot represent earlier availability.'
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'results.json').write_text(json.dumps(report, indent=2)+'\n')
    # Deterministic compressed audit rows (no generation-time gzip header).
    import io
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(predictions[0]), lineterminator='\n')
    writer.writeheader(); writer.writerows(predictions)
    (args.output / 'predictions.csv.gz').write_bytes(gzip.compress(stream.getvalue().encode(), mtime=0))
    print(json.dumps(report['results'], indent=2))
