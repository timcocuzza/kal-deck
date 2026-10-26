"""Offline college strength experiment; no app imports, network or SQLite writes.

python3 scripts/compare_college_elo.py /tmp/deck-cfb-audit docs/research/cfb-elo
Inputs: cfb_schedules_2001.csv.gz through cfb_schedules_2025.csv.gz.
Read protocol.json in the output directory for the predeclared experiment.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import gzip
import hashlib
from itertools import groupby, product
import json
import math
from pathlib import Path
import random
from statistics import mean, median


DIVISIONS = {'fbs', 'fcs'}
PHASES = {'regular', 'postseason', 'spring_regular', 'spring_postseason'}
BASE = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/cfb_schedules/'


@dataclass(frozen=True)
class Game:
    id: str
    season: int
    week: int
    kickoff: str
    day: str
    home: str
    away: str
    home_name: str
    away_name: str
    home_div: str
    away_div: str
    home_score: int
    away_score: int
    neutral: bool
    phase: str

    @property
    def margin(self):
        return self.home_score - self.away_score

    @property
    def matchup(self):
        return '-'.join(sorted((self.home_div, self.away_div)))


def parse_season(rows, season):
    """Strict identity/result validation, retaining exclusion and coverage evidence."""
    games, excluded, seen, memberships, team_days = [], Counter(), set(), {}, set()
    notices, names, all_counts = [], {}, Counter()
    for row in rows:
        if str(row.get('season')) != str(season):
            raise ValueError('Season mismatch')
        divisions = {row.get(side + '_division') for side in ('home', 'away')}
        if not divisions <= DIVISIONS:
            excluded['outside_division_i'] += 1
            continue
        gid = row.get('game_id', '')
        if not gid.isdigit() or gid in seen:
            raise ValueError('Missing/duplicate Division I game ID')
        seen.add(gid)
        for side in ('home', 'away'):
            tid, div = row.get(side + '_id', ''), row[side + '_division']
            if not tid.isdigit() or not row.get(side + '_team'):
                raise ValueError('Invalid team ID/name')
            if tid in memberships and memberships[tid] != div:
                raise ValueError('Division changes within a season')
            memberships[tid], names[tid] = div, row[side + '_team']
            all_counts[tid] += 1
        if row['home_id'] == row['away_id']:
            raise ValueError('Self matchup')
        if row.get('neutral_site') not in ('true', 'false') or row.get('completed') not in ('true', 'false'):
            raise ValueError('Unknown neutral/completion flag')
        status = row.get('status', '')
        if row['completed'] == 'false':
            if status not in ('STATUS_CANCELED', 'STATUS_CANCELLED'):
                raise ValueError(f'Unresolved historical game {gid}')
            excluded['canceled'] += 1
            notices.append({'game_id': gid, 'reason': 'Canceled; no rating update'})
            continue
        if status not in ('', 'STATUS_FINAL', 'STATUS_FINAL_OVERTIME'):
            raise ValueError('Completion and status disagree')
        if row.get('season_type') not in PHASES:
            raise ValueError('Unknown game phase')
        if not all(row.get(side + '_points', '').isdigit() for side in ('home', 'away')):
            raise ValueError('Missing/invalid final score')
        stamp = datetime.fromisoformat(row['start_date'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.year not in (season, season + 1):
            raise ValueError('Unverified kickoff/season')
        stamp = stamp.astimezone(timezone.utc)
        day = stamp.date().isoformat()
        for side in ('home', 'away'):
            key = row[side + '_id'], day
            if key in team_days:
                raise ValueError('Team plays twice on same UTC date')
            team_days.add(key)
        week = int(row['week'])
        if not 0 <= week <= 30:
            raise ValueError('Invalid week')
        games.append(Game(gid, season, week, stamp.isoformat(), day, row['home_id'], row['away_id'],
                          row['home_team'], row['away_team'], row['home_division'], row['away_division'],
                          int(row['home_points']), int(row['away_points']), row['neutral_site'] == 'true',
                          row['season_type']))
        if not status:
            excluded['included_without_status_name'] += 1
    counts = Counter(t for g in games for t in (g.home, g.away))
    graph = defaultdict(set)
    for g in games:
        graph[g.home].add(g.away)
        graph[g.away].add(g.home)
    remaining, components = set(graph), []
    while remaining:
        frontier, component = [min(remaining)], set()
        while frontier:
            team = frontier.pop()
            if team in component:
                continue
            component.add(team)
            frontier.extend(graph[team] - component)
        remaining -= component
        components.append(len(component))
    audit = {'season': season, 'source_rows': len(rows), 'completed_d1_games': len(games),
             'matchup_counts': dict(Counter(g.matchup for g in games)),
             'division_team_counts': dict(Counter(memberships.values())),
             'phases': dict(Counter(g.phase for g in games)), 'exclusions_and_notices': dict(excluded),
             'game_notices': notices, 'graph_components': sorted(components, reverse=True),
             'teams_with_fewer_than_seven_d1_results': [
                 {'id': tid, 'name': names[tid], 'division': memberships[tid], 'games': count}
                 for tid, count in sorted(counts.items()) if count < 7],
             'date_range': [min(g.day for g in games), max(g.day for g in games)],
             'coverage_note': 'Internal checks do not establish completeness. Below-DI games are intentionally excluded; low counts can also reflect transitions or the pandemic.'}
    return sorted(games, key=lambda g: (g.day, g.id)), audit


def read_history(cache):
    games, audits = [], []
    for season in range(2001, 2026):
        path = cache / f'cfb_schedules_{season}.csv.gz'
        body = path.read_bytes()
        rows = list(csv.DictReader(gzip.decompress(body).decode('utf-8-sig').splitlines()))
        try:
            parsed, audit = parse_season(rows, season)
        except ValueError as error:
            if season >= 2014:
                raise
            # Audit excluded old seasons honestly; never repair duplicate or
            # conflicting historical identities by silently dropping a row.
            parsed = []
            d1 = [r for r in rows if {r.get('home_division'), r.get('away_division')} <= DIVISIONS]
            appearances = defaultdict(list)
            for row in d1:
                for side in ('home', 'away'):
                    appearances[(row[side + '_id'], row['start_date'][:10])].append(row['game_id'])
            audit = {'season': season, 'source_rows': len(rows), 'raw_d1_rows': len(d1),
                     'validation_error': str(error), 'excluded_from_replay': True,
                     'team_date_conflicts': [{'team_id': key[0], 'date': key[1], 'game_ids': ids}
                                             for key, ids in appearances.items() if len(ids) > 1]}
        audit.update(url=BASE + path.name, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        games.extend(parsed)
        audits.append(audit)
    if len({g.id for g in games}) != len(games):
        raise ValueError('Duplicate game ID across seasons')
    games.sort(key=lambda g: (g.day, g.id))
    if [g.season for g in games] != sorted(g.season for g in games):
        raise ValueError('Source seasons overlap in calendar order; regression rule needs review')
    return games, audits


def bounded_residual(error, family, cap):
    if family == 'tanh':
        return cap * math.tanh(error / cap)
    if family == 'clip':
        return max(-cap, min(cap, error))
    if family == 'linear':
        return error
    raise ValueError('Unknown performance family')


def logistic(difference):
    tail = math.exp(-abs(difference) * math.log(10) / 400)
    return 1 / (1 + tail) if difference >= 0 else tail / (1 + tail)


def replay(games, config, *, reverse_day=False):
    """Past-only division centers, season regression and simultaneous date batches."""
    ratings, divisions, last_season = {}, {}, {}
    current_season, active, centers, season_games = None, set(), {'fbs': 0.0, 'fcs': 0.0}, Counter()
    logs = []
    for (season, day), batch_iter in groupby(games, key=lambda g: (g.season, g.day)):
        batch = list(batch_iter)
        if reverse_day:
            batch.reverse()
        if season != current_season:
            if current_season is not None:
                for division in DIVISIONS:
                    values = [ratings[t] for t in sorted(active) if divisions[t] == division]
                    if values:
                        centers[division] = mean(values)
            current_season, active, season_games = season, set(), Counter()
        for game in batch:
            for tid, div in ((game.home, game.home_div), (game.away, game.away_div)):
                if tid not in ratings:
                    ratings[tid], divisions[tid] = centers[div], div
                elif last_season[tid] != season:
                    # Retain the old division for regression on a transition. A
                    # move to FBS never injects a free FBS-center rating increase.
                    center = centers[divisions[tid]]
                    ratings[tid] = center + config['retention'] ** (season - last_season[tid]) * (ratings[tid] - center)
                last_season[tid] = season
                divisions[tid] = div
                active.add(tid)
        changes = defaultdict(float)
        for game in batch:
            before_home, before_away = ratings[game.home], ratings[game.away]
            difference = before_home - before_away + (0 if game.neutral else config['home'])
            actual = 1.0 if game.margin > 0 else 0.0 if game.margin < 0 else 0.5
            if config['family'] in ('elo', 'nfl_margin'):
                probability = logistic(difference)
                multiplier = 1.0
                if config['family'] == 'nfl_margin':
                    winner_difference = difference if game.margin > 0 else -difference
                    denominator = 2.2 + winner_difference * 0.001
                    if denominator <= 0:
                        raise ValueError('NFL margin multiplier outside valid range')
                    multiplier = math.log(abs(game.margin) + 1) * 2.2 / denominator if game.margin else math.log(2) * 2.2
                change = config['alpha'] * multiplier * (actual - probability)
            else:
                change = config['alpha'] * bounded_residual(game.margin - difference, config['family'], config['cap'])
            changes[game.home] += change
            changes[game.away] -= change
            logs.append({'game': game, 'raw_benchmark': difference, 'benchmark': difference,
                         'home_before': before_home, 'away_before': before_away, 'home_change': change,
                         'home_after': before_home + change, 'away_after': before_away - change,
                         'home_games_before': season_games[game.home], 'away_games_before': season_games[game.away],
                         'division_centers': centers.copy()})
        for team, change in changes.items():
            ratings[team] += change
            season_games[team] += 1
            if not math.isfinite(ratings[team]):
                raise ValueError('Non-finite rating')
    return sorted(logs, key=lambda row: (row['game'].day, row['game'].id))


def scoring_rows(logs, years, matchup='fbs-fbs'):
    return [r for r in logs if years[0] <= r['game'].season <= years[1]
            and (matchup is None or r['game'].matchup == matchup)]


def margin_conversion(logs, years):
    rows = scoring_rows(logs, years)
    denominator = sum(r['raw_benchmark'] ** 2 for r in rows)
    return sum(r['raw_benchmark'] * r['game'].margin for r in rows) / denominator if denominator else 0.0


def convert(logs, factor):
    return [{**r, 'benchmark': r['raw_benchmark'] * factor} for r in logs]


def metrics(rows):
    if not rows:
        return {'games': 0}
    errors = [r['benchmark'] - r['game'].margin for r in rows]
    abs_errors = sorted(abs(e) for e in errors)
    winners = [r for r in rows if r['game'].margin]
    direction = sum(0.5 if r['benchmark'] == 0 else float(r['benchmark'] * r['game'].margin > 0) for r in winners)
    return {'games': len(rows), 'mae': mean(abs_errors), 'rmse': math.sqrt(mean(e * e for e in errors)),
            'bias_predicted_minus_actual': mean(errors), 'median_absolute_error': median(abs_errors),
            'p90_absolute_error': abs_errors[math.ceil(0.9 * len(rows)) - 1],
            'winner_direction_accuracy': direction / len(winners) if winners else None,
            'winner_rating_decreases': sum(r['home_change'] * r['game'].margin < 0 for r in winners),
            'non_tied_games': len(winners)}


def evaluate(logs, years):
    return {'fbs_fbs': metrics(scoring_rows(logs, years)),
            'fbs_fcs': metrics(scoring_rows(logs, years, 'fbs-fcs')),
            'fcs_fcs': metrics(scoring_rows(logs, years, 'fcs-fcs')),
            'by_season': {str(y): metrics(scoring_rows(logs, (y, y))) for y in range(years[0], years[1] + 1)},
            'early_season_fbs_fbs': metrics([r for r in scoring_rows(logs, years)
                                            if min(r['home_games_before'], r['away_games_before']) < 3])}


def candidate_key(item):
    c = item['config']
    return (item['selection']['mae'], c['family'], c['alpha'], c['home'], c['cap'], c['retention'])


def select_candidates(games, protocol):
    """This function never receives held-out games."""
    years = protocol['selection_seasons']
    if any(g.season > years[1] for g in games):
        raise ValueError('Held-out data passed to parameter selection')
    p, candidates = protocol['performance_rating'], []
    for family, alpha, home, cap, retention in product(p['families'], p['alpha'], p['home_advantage_points'],
                                                     p['residual_cap_points'], p['offseason_retention']):
        config = dict(family=family, alpha=alpha, home=home, cap=cap, retention=retention)
        logs = replay(games, config)
        candidates.append({'config': config, 'selection': metrics(scoring_rows(logs, years)), 'conversion': 1})
    candidates.sort(key=candidate_key)
    selected = candidates[0]
    retention = {str(r): min((x for x in candidates if x['config']['retention'] == r), key=candidate_key)
                 for r in p['offseason_retention']}
    baselines = []
    for alpha, home, retain in product(p['alpha'], p['home_advantage_points'], p['offseason_retention']):
        config = dict(family='linear', alpha=alpha, home=home, cap=0, retention=retain)
        logs = replay(games, config)
        baselines.append({'config': config, 'selection': metrics(scoring_rows(logs, years)), 'conversion': 1})
    linear = min(baselines, key=candidate_key)
    elo, grid = [], protocol['win_elo_grid']
    for k, home, retain in product(grid['k'], grid['home_advantage'], grid['offseason_retention']):
        config = dict(family='elo', alpha=k, home=home, cap=0, retention=retain)
        logs = replay(games, config)
        factor = margin_conversion(logs, years)
        elo.append({'config': config, 'conversion': factor, 'selection': metrics(scoring_rows(convert(logs, factor), years))})
    nfl = dict(family='nfl_margin', alpha=20, home=50, cap=0, retention=2 / 3)
    nfl_logs = replay(games, nfl)
    nfl_conversion = margin_conversion(nfl_logs, years)
    # Ordinary two-variable least squares. Same-division games identify venue
    # effect; cross-division games identify the FBS-FCS baseline separation.
    training = [g for g in games if years[0] <= g.season <= years[1]]
    xx = xz = zz = xy = zy = 0.0
    for g in training:
        x = int(g.home_div == 'fbs') - int(g.away_div == 'fbs')
        z = int(not g.neutral)
        xx += x*x; xz += x*z; zz += z*z; xy += x*g.margin; zy += z*g.margin
    determinant = xx * zz - xz * xz
    division_only = {'gap': (xy * zz - zy * xz) / determinant, 'home': (zy * xx - xy * xz) / determinant}
    return {'candidate_counts': {'performance': len(candidates), 'linear': len(baselines), 'win_elo': len(elo)},
            'selected': selected, 'top_10': candidates[:10], 'retention_candidates': retention,
            'linear': linear, 'win_elo': min(elo, key=candidate_key),
            'nfl_margin': {'config': nfl, 'conversion': nfl_conversion,
                           'selection': metrics(scoring_rows(convert(nfl_logs, nfl_conversion), years))},
            'division_only': division_only}


def paired_interval(candidate, baseline):
    candidate_by_id = {r['game'].id: r for r in candidate}
    if set(candidate_by_id) != {r['game'].id for r in baseline}:
        raise ValueError('Paired comparison game IDs differ')
    blocks = defaultdict(list)
    for row in baseline:
        game = row['game']
        other = candidate_by_id[game.id]
        blocks[(game.season, game.phase, game.week)].append(
            abs(other['benchmark'] - game.margin) - abs(row['benchmark'] - game.margin))
    sums = [(sum(values), len(values)) for _, values in sorted(blocks.items())]
    rng, samples = random.Random(1729), []
    for _ in range(2000):
        selected = rng.choices(sums, k=len(sums))
        samples.append(sum(x for x, _ in selected) / sum(n for _, n in selected))
    samples.sort()
    return {'candidate_minus_baseline_mae': sum(x for x, _ in sums) / sum(n for _, n in sums),
            'descriptive_95_percent_block_interval': [samples[49], samples[1949]],
            'blocks': len(blocks), 'draws': 2000, 'seed': 1729}


def serializable_log(row):
    return {**{k: v for k, v in row.items() if k != 'game'}, 'game': asdict(row['game'])}


def run(cache, output):
    protocol = json.loads((output / 'protocol.json').read_text())
    history, audits = read_history(cache)
    write_json(output / 'source-audit.json', {'checked_at': datetime.now(timezone.utc).isoformat(),
               'seasons': audits, 'validated_completed_d1_games_in_nonrejected_files': len(history),
               'excluded_from_replay_years': [2001, 2013],
               'limitations': ['Source-season membership has not been independently certified against NCAA lists.',
                              'Internal consistency is not proof that every game is present.',
                              'Older FCS records are incomplete; see coverage-checks.json for endpoint spot checks.',
                              'Retrospectively corrected snapshots are used; historical publication-time versions are unavailable.',
                              'Final score margin includes overtime; no consistent regulation breakdown established.']})
    games = [g for g in history if g.season >= protocol['warmup_seasons'][0]]
    training = [g for g in games if g.season <= protocol['selection_seasons'][1]]
    selected = select_candidates(training, protocol)
    lock = {'protocol_sha256': sha256(output / 'protocol.json'), 'script_sha256': sha256(Path(__file__)),
            'training_history_sha256': hashlib.sha256(json.dumps([asdict(g) for g in training], sort_keys=True).encode()).hexdigest(),
            'created_before_held_out_scoring': True, **selected}
    write_json(output / 'selection-lock.json', lock)
    print('Settings frozen before held-out evaluation:', selected['selected']['config'], flush=True)
    logs, evaluated = {}, {}
    years = protocol['held_out_seasons']
    for name in ('selected', 'linear', 'win_elo', 'nfl_margin'):
        entry = selected[name]
        logs[name] = convert(replay(games, entry['config']), entry['conversion'])
        evaluated[name] = {'config': entry['config'], 'conversion': entry['conversion'], 'metrics': evaluate(logs[name], years)}
    simple = selected['division_only']
    logs['division_only'] = [{**r, 'benchmark': simple['gap'] * (int(r['game'].home_div == 'fbs') - int(r['game'].away_div == 'fbs'))
                             + simple['home'] * int(not r['game'].neutral), 'home_change': 0}
                            for r in logs['selected']]
    evaluated['division_only'] = {'config': simple, 'metrics': evaluate(logs['division_only'], years)}
    sensitivities = {}
    for retain, entry in selected['retention_candidates'].items():
        sensitivities['retention_' + retain] = {'config': entry['config'],
            'metrics': evaluate(replay(games, entry['config']), years)}
    high = {**selected['selected']['config'], 'retention': 2 / 3}
    sensitivities['high_carryover_diagnostic'] = {'config': high, 'metrics': evaluate(replay(games, high), years),
                                                'eligible_for_automatic_selection': False}
    sensitivities['without_fcs'] = {'metrics': evaluate(replay([g for g in games if g.matchup == 'fbs-fbs'], selected['selected']['config']), years)}
    reordered = replay(games, selected['selected']['config'], reverse_day=True)
    if any(a['benchmark'] != b['benchmark'] or a['home_change'] != b['home_change'] for a, b in zip(logs['selected'], reordered)):
        raise ValueError('Within-date result order affected predictions')
    held = scoring_rows(logs['selected'], years)
    comparisons = {name: paired_interval(held, scoring_rows(rows, years)) for name, rows in logs.items() if name != 'selected'}
    examples = [serializable_log(r) for r in held if r['home_change'] * r['game'].margin < 0][:12]
    result = {'status': 'Offline experiment; no production rating enabled', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'protocol_sha256': lock['protocol_sha256'], 'selection_lock_sha256': sha256(output / 'selection-lock.json'),
              'replayed_games': len(games), 'selection': selected, 'held_out': evaluated, 'sensitivities': sensitivities,
              'paired_comparisons': comparisons, 'within_date_order_invariant': True, 'counterintuitive_update_examples': examples}
    write_json(output / 'comparison.json', result)
    # Save raw, auditable paired pregame predictions. FCS ratings are research
    # internals only; do not pass this artifact directly to the UI.
    with gzip.open(output / 'held-out-predictions.csv.gz', 'wt', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['game_id', 'season', 'week', 'date', 'home_id', 'away_id', 'actual_margin', *logs.keys()])
        by_id = {name: {r['game'].id: r['benchmark'] for r in values} for name, values in logs.items()}
        for row in held:
            g = row['game']
            writer.writerow([g.id, g.season, g.week, g.day, g.home, g.away, g.margin, *(by_id[name][g.id] for name in logs)])
    print(json.dumps({name: row['metrics']['fbs_fbs'] for name, row in evaluated.items()}, indent=2))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.cache, args.output)
