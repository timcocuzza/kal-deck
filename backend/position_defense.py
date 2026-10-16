"""Position-group defense context from reconciled official player-game totals."""

from collections import Counter, defaultdict
from fractions import Fraction

from .matchups import canonical
from .rankings import identifier, json_numbers, league_summary, number, rank_metrics, stat_metric
from .sources.common import SourceError


POSITION_CATEGORIES = {
    'rb_receiving': ('Receiving allowed to RB/FB', ('RB', 'FB'), 'receiving'),
    'wr_receiving': ('Receiving allowed to WR', ('WR',), 'receiving'),
    'te_receiving': ('Receiving allowed to TE', ('TE',), 'receiving'),
    'rb_rushing': ('Rushing allowed to RB/FB', ('RB', 'FB'), 'rushing'),
    'qb_rushing': ('Rushing allowed to QB', ('QB',), 'rushing'),
}
FIELDS = ('receiving_yards', 'targets', 'receptions', 'receiving_tds', 'rushing_yards', 'carries', 'rushing_tds')
POSITIONS = set('QB RB FB HB WR TE T OT LT RT G OG LG RG C OL DL DT NT DE EDGE LB ILB MLB OLB CB DB S FS SS K P LS'.split())
COMPONENTS = ('designed', 'scramble', 'kneel')


def prop_position_categories(category, position):
    group = {'RB': 'rb', 'FB': 'rb', 'WR': 'wr', 'TE': 'te', 'QB': 'qb'}.get(position)
    kinds = []
    if category in ('receiving_yards', 'receptions', 'rushing_receiving_yards'):
        kinds.append('receiving')
    if category in ('rushing_yards', 'rushing_attempts', 'rushing_receiving_yards'):
        kinds.append('rushing')
    return [f'{group}_{kind}' for kind in kinds if f'{group}_{kind}' in POSITION_CATEGORIES]


def position_rank_context(teams, opponent, category, position):
    team = next((item for item in teams if item['team'] == canonical(opponent)), {})
    ranks = []
    for key in prop_position_categories(category, position):
        headline = team.get('categories', {}).get(key, {}).get('headline', {})
        ranks.append({'category': key, 'label': POSITION_CATEGORIES[key][0], 'rank': headline.get('rank'),
                      'incomplete': headline.get('incomplete', True), 'kind': 'position',
                      'value': headline.get('value')})
    return ranks


def summarize(rows, category):
    kind = POSITION_CATEGORIES[category][2]
    yards = kind + '_yards'
    opportunity = 'targets' if kind == 'receiving' else 'carries'
    supporting = {
        opportunity + '_per_game': stat_metric(rows, opportunity),
        opportunity: stat_metric(rows, opportunity, total=True),
        'yards_per_target' if kind == 'receiving' else 'yards_per_carry': stat_metric(rows, yards, opportunity),
        'touchdowns': stat_metric(rows, kind + '_tds', total=True),
    }
    if kind == 'receiving':
        supporting['receptions_per_game'] = stat_metric(rows, 'receptions')
    if category == 'qb_rushing':
        supporting.update({component + '_yards_per_game': stat_metric(rows, component)
                           for component in COMPONENTS})
    return {'headline': stat_metric(rows, yards), 'supporting': supporting}


def calculate_position_defense(season, schedule, player_stats, team_stats, plays):
    scheduled = [row for row in schedule if number(row.get('season')) == season and row.get('game_type') == 'REG']
    teams = sorted({canonical(row[key]) for row in scheduled for key in ('home_team', 'away_team')})
    completed = sorted([row for row in scheduled if all(number(row.get(key)) is not None
                        for key in ('home_score', 'away_score'))], key=lambda row: (row['gameday'], number(row['week']), row['game_id']))
    games, opponents, team_games = {}, {}, defaultdict(list)
    for game in completed:
        gid = game['game_id']
        if gid in games:
            raise SourceError('Duplicate scheduled game; position-specific rankings require review.')
        games[gid] = game
        home, away = canonical(game['home_team']), canonical(game['away_team'])
        if not home or not away or home == away:
            raise SourceError('Invalid scheduled teams; position-specific rankings require review.')
        opponents[gid, home], opponents[gid, away] = away, home
        team_games[home].append(game)
        team_games[away].append(game)

    warnings = set()
    bad = set()
    grouped, totals = defaultdict(list), defaultdict(list)
    seen_players = defaultdict(list)
    for source, destination in ((player_stats, grouped), (team_stats, totals)):
        for row in source:
            gid = row.get('game_id')
            if number(row.get('season')) != season or row.get('season_type') != 'REG' or gid not in games:
                continue
            team = canonical(row.get('team'))
            key = gid, team
            if (key not in opponents or canonical(row.get('opponent_team')) != opponents.get(key)
                    or number(row.get('week')) != number(games[gid]['week'])):
                bad.update((gid, canonical(games[gid][side])) for side in ('home_team', 'away_team'))
                warnings.add(f'{gid}: conflicting player/team statistics; position totals withheld.')
                continue
            if (source is player_stats and not any(row.get(field) for field in ('player_id', 'player_display_name', 'position'))
                    and all(number(row.get(field)) == 0 for field in FIELDS)):
                warnings.add(f'{gid} {team}: excluded an unidentified row with explicitly zero rushing/receiving contributions; team totals still require reconciliation.')
                continue
            destination[key].append(row)
            if source is player_stats:
                if not row.get('player_id'):
                    bad.add(key)
                seen_players[gid, row.get('player_id')].append(key)
    for keys in seen_players.values():
        if len(keys) > 1:
            bad.update(keys)

    # Validate each statistic independently, including players outside our five groups.
    # Agreement on both yards and opportunity counts helps distinguish zero from missing rows.
    values = {}
    for key in opponents:
        rows, team_rows = grouped[key], totals[key]
        if key in bad or not rows or len(team_rows) != 1:
            values[key] = {}
            warnings.add(f'{key[0]} {key[1]}: missing or duplicate records; position totals unavailable.')
            continue
        valid = {}
        for field in FIELDS:
            amounts = [number(row.get(field)) for row in rows]
            total = number(team_rows[0].get(field))
            if (total is None or any(value is None or value.denominator != 1
                                    or (not field.endswith('_yards') and value < 0) for value in amounts)
                    or any(row.get('position') not in POSITIONS and value != 0 for row, value in zip(rows, amounts))
                    or sum(amounts, Fraction()) != total):
                warnings.add(f'{key[0]} {key[1]}: {field} cannot be reconciled by position; affected statistics unavailable.')
            else:
                valid[field] = amounts
        values[key] = valid

    splits = qb_splits(season, games, opponents, grouped, bad, plays)
    results = []
    for team in teams:
        logs, season_rows = [], defaultdict(list)
        for game in team_games[team]:
            gid = game['game_id']
            opponent = opponents[gid, team]
            key = gid, opponent
            categories, notes = {}, []
            for category, (_, positions, kind) in POSITION_CATEGORIES.items():
                raw = {}
                for field, amounts in values[key].items():
                    raw[field] = sum((value for row, value in zip(grouped[key], amounts)
                                      if row.get('position') in positions), Fraction())
                # Do not rank an apparently complete yard total when opportunity records conflict.
                required = ('receiving_yards', 'targets', 'receptions') if kind == 'receiving' else ('rushing_yards', 'carries')
                if any(field not in raw for field in required):
                    raw = {}
                if category == 'qb_rushing':
                    breakdown = splits.get(key)
                    if breakdown is not None and all(field in raw for field in required):
                        raw.update(breakdown)
                    elif raw:
                        notes.append('QB rushing breakdown could not be verified; official totals are still shown.')
                categories[category] = summarize([raw], category)
                season_rows[category].append(raw)
            logs.append({'game_id': gid, 'week': int(number(game['week'])), 'date': game['gameday'],
                         'opponent': opponent, 'home': canonical(game['home_team']) == team,
                         'categories': categories, 'notes': notes})
        results.append({'team': team, 'games_played': len(logs), 'games': logs,
                        'categories': {key: summarize(season_rows[key], key) for key in POSITION_CATEGORIES}})
    for key in POSITION_CATEGORIES:
        rank_metrics([team['categories'][key]['headline'] for team in results], descending=False)
    return json_numbers({
        'season': season, 'completed_games': len(games), 'teams': results,
        'categories': [{'key': key, 'label': value[0], 'measure': 'Yards allowed / game', 'higher_is_better': False}
                       for key, value in POSITION_CATEGORIES.items()],
        'league': {key: league_summary([team['categories'][key]['headline'] for team in results]) for key in POSITION_CATEGORIES},
        'warnings': sorted(warnings) if scheduled else ['No regular-season schedule is available.'],
    })


def qb_splits(season, games, opponents, grouped, invalid, plays):
    """Only expose a split if yards AND attempts reconcile for every QB in that game."""
    index = {(gid, team, row.get('player_id')): row for (gid, team), rows in grouped.items() for row in rows}
    buckets = defaultdict(lambda: defaultdict(Fraction))
    carries = Counter()
    bad = set(invalid)
    seen = set()
    for play in plays:
        gid = play.get('game_id')
        if gid not in games or number(play.get('season')) != season or play.get('season_type') != 'REG':
            continue
        identity = gid, identifier(play.get('play_id'))
        if identity in seen or number(play.get('play_id')) is None:
            bad.update(key for key in opponents if key[0] == gid)
        seen.add(identity)
        if play.get('play_type') == 'no_play' or number(play.get('two_point_attempt')) == 1:
            continue
        if not any(number(play.get(flag)) == 1 for flag in ('rush_attempt', 'qb_scramble', 'qb_kneel')):
            continue
        team = canonical(play.get('posteam'))
        key = gid, team
        if opponents.get(key) != canonical(play.get('defteam')):
            bad.update(k for k in opponents if k[0] == gid)
            continue
        player_key = gid, team, play.get('rusher_player_id')
        player = index.get(player_key)
        lateral_id = play.get('lateral_rusher_player_id')
        if lateral_id:
            lateral = index.get((gid, team, lateral_id))
            if lateral is None or lateral.get('position') == 'QB':
                bad.add(key)  # A lateral recipient does not establish a QB designed run/scramble.
        if player is None or player.get('position') not in POSITIONS:
            bad.add(key)
            continue
        if player.get('position') != 'QB':
            continue
        scramble, kneel = number(play.get('qb_scramble')), number(play.get('qb_kneel'))
        yards = number(play.get('rushing_yards'))
        if (yards is None or yards.denominator != 1 or scramble not in (0, 1) or kneel not in (0, 1)
                or scramble + kneel > 1 or number(play.get('rush_attempt')) != 1
                or number(play.get('two_point_attempt')) != 0):
            bad.add(key)
            continue
        component = 'kneel' if kneel else 'scramble' if scramble else 'designed'
        buckets[player_key][component] += yards
        carries[player_key] += 1
    result = {}
    for key, rows in grouped.items():
        qbs = [row for row in rows if row.get('position') == 'QB']
        if key in bad:
            continue
        total = dict.fromkeys(COMPONENTS, Fraction())
        for row in qbs:
            player_key = *key, row['player_id']
            bucket = buckets[player_key]
            if sum(bucket.values(), Fraction()) != number(row.get('rushing_yards')) or carries[player_key] != number(row.get('carries')):
                break
            for component in COMPONENTS:
                total[component] += bucket[component]
        else:
            result[key] = total
    return result
