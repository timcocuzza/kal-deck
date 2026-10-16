"""Approved season calculations. Exact ratios are retained until JSON serialization."""

from collections import defaultdict
from fractions import Fraction
from statistics import median

from .sources.common import SourceError


CATEGORIES = {
    'passing_offense': ('Passing offense', 'EPA / dropback', True, 'passing_defense'),
    'passing_defense': ('Passing defense', 'EPA allowed / dropback', False, 'passing_offense'),
    'rushing_offense': ('Rushing offense', 'EPA / designed run', True, 'rushing_defense'),
    'rushing_defense': ('Rushing defense', 'EPA allowed / designed run', False, 'rushing_offense'),
    'pass_rush': ('Pass rush', 'Sacks / game', True, 'pass_protection'),
    'pass_protection': ('Pass protection', 'Sacks allowed / game', False, 'pass_rush'),
}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None


def flag(row, key):
    return number(row.get(key)) == 1


def mean(values):
    usable = [value for value in values if value is not None]
    return sum(usable, Fraction()) / len(usable) if usable else None


def league_summary(metrics):
    """Each available team's season value has one vote, regardless of sample size."""
    values = [item['value'] for item in metrics if item['value'] is not None]
    return {
        'mean': mean(values),
        'median': median(values) if values else None,
        'teams_used': len(values),
        'teams_expected': len(metrics),
        'incomplete': not values or len(values) < len(metrics) or any(item['incomplete'] for item in metrics),
    }


def metric(value, used, expected, *, samples_used=None, samples_expected=None, incomplete=False):
    return {
        'value': value,
        'coverage': {
            'games_used': used, 'games_expected': expected,
            'samples_used': samples_used, 'samples_expected': samples_expected,
        },
        'incomplete': incomplete or used < expected or value is None or (
            samples_used is not None and samples_used < samples_expected
        ),
    }


def play_metric(values, success=False):
    valid = [v for v in values if v is not None]
    value = mean([Fraction(v > 0) for v in valid] if success else valid)
    if success and value is not None:
        value *= 100
    return metric(value, int(value is not None), 1, samples_used=len(valid), samples_expected=len(values))


def game_mean(metrics):
    values = [m['value'] for m in metrics]
    with_samples = [m for m in metrics if m['coverage']['samples_used'] is not None]
    return metric(mean(values), sum(v is not None for v in values), len(metrics),
                  samples_used=sum(m['coverage']['samples_used'] for m in with_samples) if with_samples else None,
                  samples_expected=sum(m['coverage']['samples_expected'] for m in with_samples) if with_samples else None,
                  incomplete=any(m['incomplete'] for m in metrics))


def stat_metric(rows, numerator, denominator=None, *, total=False, percentage=False):
    pairs = []
    for row in rows:
        value = number(row.get(numerator))
        divisor = number(row.get(denominator)) if denominator else Fraction(1)
        if value is not None and divisor is not None and divisor >= 0:
            pairs.append((value, divisor))
    value = None
    if pairs:
        numerator_sum = sum((pair[0] for pair in pairs), Fraction())
        divisor_sum = sum((pair[1] for pair in pairs), Fraction())
        if total:
            value = numerator_sum
        elif divisor_sum > 0:
            value = numerator_sum / divisor_sum * (100 if percentage else 1)
    return metric(value, len(pairs) if value is not None else 0, len(rows))


def support(rows, kind):
    if kind == 'passing':
        return {
            'yards_per_game': stat_metric(rows, 'passing_yards'),
            'yards_per_attempt': stat_metric(rows, 'passing_yards', 'attempts'),
            'completion_percentage': stat_metric(rows, 'completions', 'attempts', percentage=True),
            'touchdowns': stat_metric(rows, 'passing_tds', total=True),
            'interceptions': stat_metric(rows, 'passing_interceptions', total=True),
        }
    return {
        'yards_per_game': stat_metric(rows, 'rushing_yards'),
        'yards_per_carry': stat_metric(rows, 'rushing_yards', 'carries'),
        'touchdowns': stat_metric(rows, 'rushing_tds', total=True),
    }


def identifier(value):
    parsed = number(value)
    return str(parsed.numerator) if parsed is not None and parsed.denominator == 1 else str(value)


def rank_metrics(metrics, descending):
    for item in metrics:
        item['rank'] = None
    ordered = sorted((item for item in metrics if item['value'] is not None),
                     key=lambda item: item['value'], reverse=descending)
    previous = None
    rank = None
    for position, item in enumerate(ordered, 1):
        if item['value'] != previous:
            rank = position
            previous = item['value']
        item['rank'] = rank


def assign_ranks(teams):
    for category, (_, _, descending, _) in CATEGORIES.items():
        rank_metrics([team['categories'][category]['headline'] for team in teams], descending)


def json_numbers(value):
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, dict):
        return {key: json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_numbers(item) for item in value]
    return value


def calculate_rankings(season, schedule, team_stats, plays, charting):
    season_games = [row for row in schedule if number(row.get('season')) == season and row.get('game_type') == 'REG']
    teams = sorted({row[key] for row in season_games for key in ('home_team', 'away_team')})
    completed = [row for row in season_games if all(number(row.get(key)) is not None for key in ('home_score', 'away_score'))]
    completed.sort(key=lambda row: (row['gameday'], number(row['week']), row['game_id']))
    games = {}
    opponents = {}
    team_games = defaultdict(list)
    for game in completed:
        game_id = game['game_id']
        if game_id in games:
            raise SourceError('Duplicate scheduled game; rankings were not calculated.')
        games[game_id] = game
        home, away = game['home_team'], game['away_team']
        opponents[game_id, home] = away
        opponents[game_id, away] = home
        team_games[home].append(game)
        team_games[away].append(game)

    stats = {}
    for row in team_stats:
        if number(row.get('season')) != season or row.get('season_type') != 'REG' or row.get('game_id') not in games:
            continue
        key = row['game_id'], row['team']
        if key in stats or opponents.get(key) != row.get('opponent_team'):
            raise SourceError('Team statistics contain duplicate or mismatched game/team records.')
        stats[key] = row

    charts = {}
    for row in charting:
        if number(row.get('season')) != season or row.get('nflverse_game_id') not in games:
            continue
        key = row['nflverse_game_id'], identifier(row.get('nflverse_play_id'))
        if key in charts:
            raise SourceError('Duplicate FTN play identifiers; blitz rate was not calculated.')
        count = number(row.get('n_blitzers'))
        charts[key] = Fraction(count >= 1) * 100 if count is not None and count >= 0 and count.denominator == 1 else None

    buckets = defaultdict(list)
    seen_plays = set()
    for row in plays:
        game_id = row.get('game_id')
        if game_id not in games or number(row.get('season')) != season or row.get('season_type') != 'REG':
            continue
        key = game_id, identifier(row.get('play_id'))
        if key in seen_plays:
            raise SourceError('Duplicate play identifiers; rankings were not calculated.')
        seen_plays.add(key)
        if any(flag(row, name) for name in ('qb_kneel', 'qb_spike', 'two_point_attempt')):
            continue
        passing = flag(row, 'pass') or flag(row, 'qb_dropback') or flag(row, 'qb_scramble') or flag(row, 'sack')
        rushing = (flag(row, 'rush') or flag(row, 'rush_attempt')) and not passing
        if not (passing or rushing):
            continue
        offense, defense = row.get('posteam'), row.get('defteam')
        if opponents.get((game_id, offense)) != defense:
            raise SourceError('A classified play has missing or mismatched teams; rankings were not calculated.')
        kind = 'passing' if passing else 'rushing'
        epa = number(row.get('epa'))
        buckets[game_id, offense, f'{kind}_offense'].append(epa)
        buckets[game_id, defense, f'{kind}_defense'].append(epa)
        if passing and row.get('play_type') != 'no_play':
            buckets[game_id, defense, 'blitz'].append(charts.get(key))

    results = []
    for team in teams:
        logs = []
        for game in team_games[team]:
            game_id = game['game_id']
            opponent = opponents[game_id, team]
            own, other = stats.get((game_id, team), {}), stats.get((game_id, opponent), {})
            categories = {}
            for category in CATEGORIES:
                if category in ('pass_rush', 'pass_protection'):
                    headline = stat_metric([own], 'def_sacks' if category == 'pass_rush' else 'sacks_suffered')
                    supporting = {}
                else:
                    kind, side = category.split('_')
                    observations = buckets[game_id, team, category]
                    headline = play_metric(observations)
                    supporting = support([own if side == 'offense' else other], kind)
                    if kind == 'rushing':
                        supporting['success_percentage'] = play_metric(observations, success=True)
                categories[category] = {'headline': headline, 'supporting': supporting}
            logs.append({
                'game_id': game_id, 'week': int(number(game['week'])), 'date': game['gameday'],
                'opponent': opponent, 'home': game['home_team'] == team, 'categories': categories,
                'blitz': play_metric(buckets[game_id, team, 'blitz']),
            })
        categories = {}
        for category in CATEGORIES:
            headline = game_mean([log['categories'][category]['headline'] for log in logs])
            headline['rank'] = None
            supporting = {}
            if category not in ('pass_rush', 'pass_protection'):
                kind, side = category.split('_')
                stat_rows = [stats.get((log['game_id'], team if side == 'offense' else log['opponent']), {}) for log in logs]
                supporting = support(stat_rows, kind)
                if kind == 'rushing':
                    supporting['success_percentage'] = game_mean([log['categories'][category]['supporting']['success_percentage'] for log in logs])
            categories[category] = {'headline': headline, 'supporting': supporting}
        results.append({'team': team, 'games_played': len(logs), 'categories': categories,
                        'blitz': game_mean([log['blitz'] for log in logs]), 'games': logs})

    assign_ranks(results)
    rank_metrics([team['blitz'] for team in results], descending=True)
    indexed = {team['team']: team for team in results}
    for team in results:
        for log in team['games']:
            opponent = indexed[log['opponent']]
            for category, (_, _, _, opposite) in CATEGORIES.items():
                other = opponent['categories'][opposite]['headline']
                log['categories'][category]['opponent_current_rank'] = other['rank']
                log['categories'][category]['opponent_rank_incomplete'] = other['incomplete']
                if category in ('pass_rush', 'pass_protection'):
                    key = 'opponent_sacks_allowed_per_game' if category == 'pass_rush' else 'opponent_sacks_per_game'
                    log['categories'][category]['supporting'][key] = other.copy()
        for category, key in [('pass_rush', 'opponent_sacks_allowed_per_game'), ('pass_protection', 'opponent_sacks_per_game')]:
            # One opponent season rate per meeting, including repeat opponents and head-to-head games.
            contexts = [log['categories'][category]['supporting'][key] for log in team['games']]
            value = mean([item['value'] for item in contexts])
            team['categories'][category]['supporting'][key] = metric(
                value, sum(item['value'] is not None for item in contexts), len(contexts),
                incomplete=any(item['incomplete'] for item in contexts),
            )
    return json_numbers({
        'season': season, 'phase': 'REG', 'completed_games': len(games),
        'categories': [{'key': key, 'label': value[0], 'measure': value[1], 'higher_is_better': value[2]} for key, value in CATEGORIES.items()],
        'blitz_label': 'FTN-charted blitz rate', 'teams': results,
        'league': {
            'categories': {key: league_summary([team['categories'][key]['headline'] for team in results]) for key in CATEGORIES},
            'blitz': league_summary([team['blitz'] for team in results]),
        },
        'warnings': [] if season_games else ['No regular-season schedule is available for this season.'],
    })
