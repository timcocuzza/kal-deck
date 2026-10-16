"""Verified player thresholds and current-season player game logs."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

from .matchups import canonical, kickoff, valid_target
from .rankings import CATEGORIES, number
from .position_defense import prop_position_categories, position_rank_context
from .sources.kalshi import quote_midpoint
from .sources.kalshi_metadata import timestamp


# Source name: series, display label, contract statistic, nflverse fields, opponent ranks.
PROP_TYPES = {
    'passing_yards': ('KXNFLPASSYDS', 'Passing yards', 'passing yards', ('passing_yards',), ('passing_defense',)),
    'rushing_yards': ('KXNFLRSHYDS', 'Rushing yards', 'rushing yards', ('rushing_yards',), ('rushing_defense',)),
    'receiving_yards': ('KXNFLRECYDS', 'Receiving yards', 'receiving yards', ('receiving_yards',), ('passing_defense',)),
    'receptions': ('KXNFLREC', 'Receptions', 'receptions', ('receptions',), ('passing_defense',)),
    'passing_tds': ('KXNFLPASSTDS', 'Passing touchdowns', 'passing touchdowns', ('passing_tds',), ('passing_defense',)),
    'passing_attempts': ('KXNFLPASSATT', 'Passing attempts', 'passing attempts', ('attempts',), ('passing_defense',)),
    'passing_completions': ('KXNFLPASSCOMP', 'Passing completions', 'passing completions', ('completions',), ('passing_defense',)),
    'passing_interceptions': ('KXNFLPASSINT', 'Interceptions thrown', 'passing interceptions', ('passing_interceptions',), ('passing_defense',)),
    'rushing_attempts': ('KXNFLRSHATT', 'Rushing attempts', 'rushing attempts', ('carries',), ('rushing_defense',)),
    'rushing_receiving_yards': ('KXNFLRRYDS', 'Rushing + receiving yards', 'rushing and receiving yards combined',
                              ('rushing_yards', 'receiving_yards'), ('rushing_defense', 'passing_defense')),
}
SERIES_TYPES = {value[0]: key for key, value in PROP_TYPES.items()}
OTHER_LABELS = {
    'KXNFLFIRSTTD': 'First touchdown scorer', 'KXNFLTD': 'Touchdowns scored',
    'KXNFLLONGREC': 'Longest reception', 'KXNFLLONGRSH': 'Longest rush',
    'KXNFLFFPTS': 'Fantasy points', 'KXNFLFFPTSLADDER': 'Fantasy points · variable payout',
    'KXNFLSACK': 'Player sacks', 'KXNFLTKL': 'Player tackles', 'KXNFLINT': 'Defensive interceptions',
    'KXNFLRSHYDSH2H': 'Rushing yards · head to head',
    'KXNFLRECYDSH2H': 'Receiving yards · head to head',
    'KXNFLPASSYDSH2H': 'Passing yards · head to head',
    'KXNFLMOSTRECYDS': 'Most receiving yards', 'KXNFLMOSTRSHYDS': 'Most rushing yards',
}


def player_index(season, stats, depth):
    """Exact names and canonical teams only; never collapse distinct NFL IDs."""
    index = defaultdict(lambda: defaultdict(set))
    for row in stats:
        if str(row.get('season')) == str(season) and row.get('season_type') == 'REG' and row.get('player_id'):
            index[(row.get('player_display_name'), canonical(row.get('team')))][row['player_id']].add(row.get('position'))
    latest = {}
    for row in depth:
        team = canonical(row.get('team'))
        latest[team] = max(latest.get(team, ''), row.get('dt') or '')
    for row in depth:
        team = canonical(row.get('team'))
        if row.get('gsis_id') and row.get('dt') == latest[team]:
            index[(row.get('player_name'), team)][row['gsis_id']].add(row.get('pos_abb'))
    return index


def unique_records(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return {identifier: values[0] for identifier, values in grouped.items() if identifier and len(values) == 1}


def verify_player(market, milestone, players, targets, index):
    strike = market.get('custom_strike')
    if not isinstance(strike, dict):
        raise ValueError('Player or team identity is missing.')
    player = players.get(strike.get('football_player'))
    team = targets.get(strike.get('football_team'))
    details = milestone['details']
    if not player or not team or player.get('type') != 'football_player':
        raise ValueError('Player or team identity is missing or ambiguous.')
    pd = player.get('details', {})
    if (pd.get('league') != 'NFL' or pd.get('team_id') != team['id']
            or team['id'] not in (details['home_team_id'], details['away_team_id'])
            or player['id'] not in details.get('player_id_mapping', {}).values()):
        raise ValueError('Player, team and game identities disagree; refresh and review.')
    code = canonical(team['details']['abbreviation'])
    candidates = index.get((player['name'], code), {})
    if len(candidates) != 1:
        raise ValueError('No unique exact name-and-team match in nflverse; player log requires review.')
    gsis_id, positions = next(iter(candidates.items()))
    if not pd.get('position') or pd['position'] not in positions:
        raise ValueError('Player positions disagree or are missing; matching requires review.')
    return {'id': gsis_id, 'kalshi_id': player['id'], 'name': player['name'], 'team': code, 'position': pd['position']}


def threshold_view(market, category, player, milestone, targets):
    series, _, statistic, _, _ = PROP_TYPES[category]
    if (market.get('market_type') != 'binary' or market.get('strike_type') != 'greater'
            or market.get('cap_strike') is not None
            or market.get('status') not in ('active', 'open')
            or not market.get('event_ticker', '').startswith(series + '-')
            or not market.get('ticker', '').startswith(market['event_ticker'] + '-')):
        raise ValueError('Unrecognized or inactive threshold contract.')
    try:
        strike = Decimal(str(market.get('floor_strike')))
        if not strike.is_finite() or strike < 0 or strike % 1 != Decimal('0.5'):
            raise ValueError('Prop threshold requires review.')
    except InvalidOperation as error:
        raise ValueError('Prop threshold is missing or malformed.') from error
    threshold = int(strike + Decimal('0.5'))
    wording = f"{player['name']}: {threshold}+"
    if market.get('title') != f'{wording} {statistic}' or market.get('yes_sub_title') != wording:
        raise ValueError('Prop title disagrees with its player, statistic or threshold.')
    rules = re.fullmatch(r'If (.+) records ([0-9]+)\+ (.+) in the (.+) vs (.+) (?i:Pro(?:fessional)? Football) game originally scheduled for (.+), then the market resolves to Yes\.',
                         market.get('rules_primary', ''))
    details = milestone['details']
    names = {targets[details[key]]['name'] for key in ('home_team_id', 'away_team_id')}
    game_date = timestamp(milestone['start_date']).astimezone(ZoneInfo('America/New_York')).date()
    if (not rules or rules[1] != player['name'] or int(rules[2]) != threshold or rules[3] != statistic
            or {rules[4], rules[5]} != names or datetime.strptime(rules[6], '%b %d, %Y').date() != game_date):
        raise ValueError('Prop settlement wording disagrees with its player, statistic, threshold or game.')
    quotes = {}
    for field in ('yes_bid_dollars', 'yes_ask_dollars', 'no_bid_dollars', 'no_ask_dollars'):
        try:
            quote = Decimal(str(market.get(field)))
            quotes[field] = str(quote) if quote.is_finite() and 0 < quote < 1 else None
        except InvalidOperation:
            quotes[field] = None
    midpoint = quote_midpoint(market)
    return {'ticker': market['ticker'], 'threshold': threshold, 'label': f'{threshold}+',
            'title': market['title'], 'rules': market['rules_primary'],
            'rules_secondary': market.get('rules_secondary') or '',
            'midpoint': float(midpoint) if midpoint is not None else None, **quotes}


def build_props(season, game_id, schedule, markets, milestones, team_targets, player_targets, stats, depth, now=None):
    now = now or datetime.now(timezone.utc)
    result = {'season': season, 'game_id': game_id, 'groups': [], 'issues': [], 'unsupported': [], 'warnings': []}
    candidates = [g for g in schedule if g.get('game_id') == game_id and str(g.get('season')) == str(season) and g.get('game_type') == 'REG']
    if len(candidates) != 1:
        result['warnings'].append('No unique regular-season game in the saved schedule.')
        return result
    game = candidates[0]
    same_matchup = [g for g in schedule if str(g.get('season')) == str(season) and g.get('game_type') == 'REG'
                    and str(g.get('week')) == str(game['week'])
                    and canonical(g.get('home_team')) == canonical(game['home_team'])
                    and canonical(g.get('away_team')) == canonical(game['away_team'])]
    if len(same_matchup) != 1:
        result['warnings'].append('Duplicate schedule matchup; game matching requires review.')
        return result
    start = kickoff(game)
    result['kickoff'] = start.isoformat() if start else None
    if start is None or start <= now or any(game.get(key) not in (None, '') for key in ('home_score', 'away_score')):
        result['warnings'].append('Player props are available here only for verified, unstarted games.')
        return result
    targets = unique_records([t for t in team_targets if valid_target(t)], lambda t: t['id'])
    codes = unique_records(list(targets.values()), lambda t: canonical(t['details']['abbreviation']))
    targets = {t['id']: t for t in codes.values()}
    links = []
    for milestone in milestones:
        details = milestone.get('details', {})
        phase = details.get('season', {})
        home, away = targets.get(details.get('home_team_id')), targets.get(details.get('away_team_id'))
        if (home and away and milestone.get('type') == 'football_game' and details.get('league') == 'NFL'
                and str(phase.get('year')) == str(season) and phase.get('type') == 'REG'
                and str(phase.get('week')) == str(game['week'])
                and canonical(home['details']['abbreviation']) == canonical(game['home_team'])
                and canonical(away['details']['abbreviation']) == canonical(game['away_team'])
                and timestamp(milestone.get('start_date')) == start):
            links.append(milestone)
    if len(links) != 1:
        result['warnings'].append('Missing or ambiguous Kalshi game identity; refresh and review.')
        return result
    milestone = links[0]
    events = set(milestone.get('related_event_tickers', []) + milestone.get('primary_event_tickers', []))
    ambiguous_events = {e for m in milestones if m is not milestone
                        for e in m.get('related_event_tickers', []) + m.get('primary_event_tickers', []) if e in events}
    # All other linked market series remain visible, without claiming their quotes or logs are supported.
    team_series = {'KXNFLGAME', 'KXNFLSPREAD', 'KXNFLTOTAL', 'KXNFLTIE'}
    result['unsupported'] = [{'series': s, 'label': OTHER_LABELS.get(s, s),
                              'events': sorted(e for e in events if e.split('-')[0] == s)}
                             for s in sorted({e.split('-')[0] for e in events} - set(SERIES_TYPES) - team_series)]
    players = unique_records(player_targets, lambda p: p.get('id'))
    index = player_index(season, stats, depth)
    groups = {}
    ticker_counts = defaultdict(int)
    for market in markets:
        ticker_counts[market.get('ticker')] += 1
    for market in markets:
        event = market.get('event_ticker')
        if event not in events:
            continue
        category = SERIES_TYPES.get(event.split('-')[0])
        if category is None:
            continue
        try:
            if event in ambiguous_events or ticker_counts[market.get('ticker')] != 1:
                raise ValueError('Duplicate contract or ambiguous game event; review required.')
            player = verify_player(market, milestone, players, targets, index)
            view = threshold_view(market, category, player, milestone, targets)
            key = (player['kalshi_id'], category)
            group = groups.setdefault(key, {'key': ':'.join(key), 'category': category,
                                           'label': PROP_TYPES[category][1], 'player': player, 'markets': [],
                                           'opponent': canonical(game['home_team']) if player['team'] == canonical(game['away_team']) else canonical(game['away_team']),
                                           'position_categories': prop_position_categories(category, player['position'])})
            group['markets'].append(view)
        except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation) as error:
            result['issues'].append({'market': market.get('ticker'), 'reason': str(error) or 'Malformed prop data.'})
    for group in groups.values():
        group['markets'].sort(key=lambda m: (m['threshold'], m['ticker']))
    result['groups'] = sorted(groups.values(), key=lambda g: (g['player']['team'], g['player']['name'], g['label']))
    return result


def build_player_log(season, player_id, category, schedule, stats, ranking_teams, position_teams=None):
    _, label, _, fields, rank_categories = PROP_TYPES[category]
    schedule_by_id = unique_records([g for g in schedule if str(g.get('season')) == str(season)
                                    and g.get('game_type') == 'REG'], lambda g: g.get('game_id'))
    teams = {t['team']: t for t in ranking_teams}
    records = defaultdict(list)
    for row in stats:
        if str(row.get('season')) == str(season) and row.get('season_type') == 'REG' and row.get('player_id') == player_id:
            records[row.get('game_id')].append(row)
    rows, warnings = [], []
    for game_id, matches in records.items():
        game = schedule_by_id.get(game_id)
        if not game or any(number(game.get(key)) is None for key in ('home_score', 'away_score')):
            warnings.append(f'{game_id}: player row has no verified completed game in the saved schedule.')
            continue
        if len(matches) != 1:
            warnings.append(f'{game_id}: duplicate player rows; statistics withheld.')
            continue
        row = matches[0]
        team, opponent = canonical(row.get('team')), canonical(row.get('opponent_team'))
        if ({team, opponent} != {canonical(game['home_team']), canonical(game['away_team'])}
                or team == opponent or str(row.get('week')) != str(game['week'])):
            warnings.append(f'{game_id}: player team, opponent or week conflicts with the schedule.')
            continue
        values = [number(row.get(field)) for field in fields]
        value = float(sum(values)) if all(v is not None for v in values) else None
        ranks = []
        for key in rank_categories:
            metric = teams.get(opponent, {}).get('categories', {}).get(key, {}).get('headline', {})
            ranks.append({'category': key, 'label': CATEGORIES[key][0], 'rank': metric.get('rank'),
                          'incomplete': metric.get('incomplete', True)})
        if position_teams is not None:
            ranks.extend(position_rank_context(position_teams, opponent, category, row.get('position')))
        rows.append({'game_id': game_id, 'date': game['gameday'], 'week': int(game['week']),
                     'team': team, 'opponent': opponent, 'value': value, 'opponent_ranks': ranks,
                     'components': {field: float(v) if v is not None else None for field, v in zip(fields, values)}})
    rows.sort(key=lambda r: (r['date'], r['week'], r['game_id']), reverse=True)
    return {'season': season, 'player_id': player_id, 'category': category, 'label': label,
            'games': rows, 'warnings': warnings,
            'note': 'Current-season regular season, including overtime. Only recorded player-game rows are shown; absent rows are not treated as zero or as confirmed DNPs. Opponent ranks use current season values. Official player rushing includes scrambles and kneeldowns.'}
