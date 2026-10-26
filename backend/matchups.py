"""Strict, explainable links between scheduled NFL games and Kalshi spreads."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

from .sources.kalshi import quote_midpoint, select_default_spread
from .sources.kalshi_metadata import timestamp

ALIASES = {'JAC': 'JAX', 'LAR': 'LA'}
TEAM_NAMES = {
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
    'KC': 'Kansas City Chiefs', 'LA': 'Los Angeles Rams', 'LAC': 'Los Angeles Chargers',
    'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
    'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
    'SEA': 'Seattle Seahawks', 'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders',
}


def canonical(code):
    return ALIASES.get(code, code)


def kickoff(game):
    try:
        return datetime.fromisoformat(game['gameday'] + 'T' + game['gametime']).replace(
            tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
    except (TypeError, ValueError, KeyError):
        return None


def valid_target(target):
    details = target.get('details', {})
    code = canonical(details.get('abbreviation'))
    return target.get('type') == 'football_team' and details.get('league') == 'NFL' and code in TEAM_NAMES


def contract_view(market, milestone, targets, *, league='NFL'):
    details = milestone['details']
    target = targets.get(market.get('custom_strike', {}).get('football_team'))
    if not target or target['id'] not in (details['home_team_id'], details['away_team_id']):
        raise ValueError('Contract participant does not match the game.')
    if market.get('market_type') != 'binary' or market.get('strike_type') != 'greater':
        raise ValueError('Unrecognized spread contract type.')
    if not market.get('ticker', '').startswith(market['event_ticker'] + '-'):
        raise ValueError('Contract identifier disagrees with its event.')
    try:
        strike = Decimal(str(market['floor_strike']))
        if not strike.is_finite() or strike <= 0 or strike % 1 != Decimal('0.5'):
            raise ValueError('Spread threshold needs review.')
    except (KeyError, InvalidOperation) as error:
        raise ValueError('Spread threshold is missing or invalid.') from error
    pattern = r'(.+) wins by over ([0-9.]+) points\??'
    for key in ('title', 'yes_sub_title'):
        match = re.fullmatch(pattern, market.get(key, ''))
        try:
            matches = match and match[1] == target['name'] and Decimal(match[2]) == strike
        except InvalidOperation:
            matches = False
        if not matches:
            raise ValueError('Contract wording disagrees with its participant or threshold.')
    competition = 'college football' if league == 'NCAAFB' else 'Pro Football'
    rules = re.fullmatch(r'If (.+) wins by more than ([0-9.]+) points in the (.+) vs (.+) ' + competition + r' game originally scheduled for (.+), then the market resolves to Yes\.',
                         market.get('rules_primary', ''))
    try:
        game_date = timestamp(milestone['start_date']).astimezone(ZoneInfo('America/New_York')).date()
        names = {targets[details[key]]['name'] for key in ('home_team_id', 'away_team_id')}
        rules_agree = (rules and rules[1] == target['name'] and Decimal(rules[2]) == strike
                       and {rules[3], rules[4]} == names
                       and datetime.strptime(rules[5], '%b %d, %Y').date() == game_date)
    except (InvalidOperation, ValueError, AttributeError):
        rules_agree = False
    if not rules_agree:
        raise ValueError('Contract settlement wording needs review: team, threshold or date could not be verified.')
    midpoint = quote_midpoint(market)
    quotes = {}
    for field in ('yes_bid_dollars', 'yes_ask_dollars', 'no_bid_dollars', 'no_ask_dollars'):
        try:
            quote = Decimal(str(market.get(field)))
            quotes[field] = str(quote) if quote.is_finite() and 0 < quote < 1 else None
        except InvalidOperation:
            quotes[field] = None
    label_team = target['name'] if league == 'NCAAFB' else canonical(target['details']['abbreviation'])
    return {
        'ticker': market['ticker'], 'event_ticker': market['event_ticker'],
        'team': label_team, 'spread': -float(strike),
        'label': f"{label_team} −{strike}",
        'wording': market['yes_sub_title'], 'rules': market['rules_primary'],
        'midpoint': float(midpoint) if midpoint is not None else None, **quotes,
    }


def build_matchups(season, schedule, markets, milestones, team_targets, week=None, now=None):
    now = now or datetime.now(timezone.utc)
    issues = []
    targets = {}
    by_code = {}
    invalid_ids = set()
    for target in team_targets:
        if not valid_target(target):
            issues.append({'event': None, 'reason': 'Unrecognized NFL team identity; matching requires review.'})
            continue
        code = canonical(target['details']['abbreviation'])
        if target['id'] in targets or code in by_code:
            invalid_ids.update([target['id'], by_code.get(code, {}).get('id')])
            issues.append({'event': None, 'reason': f'Duplicate team identity for {code}.'})
        targets[target['id']] = target
        by_code[code] = target
    targets = {key: row for key, row in targets.items() if key not in invalid_ids}
    by_code = {code: row for code, row in by_code.items() if row['id'] in targets}
    games = [g for g in schedule if str(g.get('season')) == str(season) and g.get('game_type') == 'REG']
    weeks = sorted({int(g['week']) for g in games})
    future = [g for g in games if (kickoff(g) is None or kickoff(g) > now)
              and g.get('home_score') in (None, '') and g.get('away_score') in (None, '')]
    selected_week = week if week is not None else min((int(g['week']) for g in future), default=weeks[-1] if weeks else 1)
    grouped = defaultdict(list)
    for market in markets:
        grouped[market['event_ticker']].append(market)
    event_links = defaultdict(list)
    for m in milestones:
        for event in set(m.get('primary_event_tickers', []) + m.get('related_event_tickers', [])):
            event_links[event].append(m)
    matched = defaultdict(list)
    for event, contracts in grouped.items():
        links = event_links.get(event, [])
        if len(links) != 1:
            issues.append({'event': event, 'reason': 'Missing or ambiguous game identity.'})
            continue
        m = links[0]
        details = m.get('details', {})
        phase = details.get('season', {})
        home, away = targets.get(details.get('home_team_id')), targets.get(details.get('away_team_id'))
        if not home or not away or details.get('league') != 'NFL' or str(phase.get('year')) != str(season) or phase.get('type') != 'REG':
            issues.append({'event': event, 'reason': 'Game teams or season could not be verified.'})
            continue
        candidates = [g for g in games if g['home_team'] == canonical(home['details']['abbreviation'])
                      and g['away_team'] == canonical(away['details']['abbreviation'])
                      and str(g['week']) == str(phase.get('week'))]
        if len(candidates) != 1 or kickoff(candidates[0]) is None or kickoff(candidates[0]) != timestamp(m.get('start_date')):
            issues.append({'event': event, 'reason': 'Schedule teams, week or kickoff disagree; refresh and review.'})
            continue
        g = candidates[0]
        views, eligible = [], []
        for contract in contracts:
            try:
                views.append(contract_view(contract, m, targets))
                eligible.append(contract)
            except ValueError as error:
                issues.append({'event': event, 'market': contract.get('ticker'), 'reason': str(error)})
            except (TypeError, AttributeError, KeyError, InvalidOperation):
                issues.append({'event': event, 'market': contract.get('ticker'),
                               'reason': 'Contract data is incomplete or malformed; review required.'})
        matched[g['game_id']].append((m, views, eligible))
    output = []
    for game in sorted(future, key=lambda g: (g['gameday'], g.get('gametime') or '', g['game_id'])):
        if int(game['week']) != selected_week:
            continue
        records = matched.get(game['game_id'], [])
        views, eligible = [], []
        if len(records) == 1:
            _, views, eligible = records[0]
        elif len(records) > 1:
            issues.append({'event': None, 'reason': f"Multiple spread events match {game['game_id']}; review required."})
        default = select_default_spread(eligible)
        start = kickoff(game)
        def team(code):
            target = by_code.get(code, {})
            logo = target.get('details', {}).get('image_url')
            if not isinstance(logo, str) or not logo.startswith('https://assets.kalshi.com/structured_targets/'):
                logo = None
            return {'code': code, 'name': TEAM_NAMES.get(code, code), 'logo': logo}
        output.append({
            'game_id': game['game_id'], 'week': selected_week,
            'kickoff': start.isoformat() if start else None, 'date': game['gameday'],
            'home': team(game['home_team']), 'away': team(game['away_team']),
            'neutral': game.get('location') == 'Neutral', 'stadium': game.get('stadium'),
            'markets': sorted(views, key=lambda v: (v['team'], v['spread'])),
            'default_market_ticker': default['ticker'] if default else None,
            'spread_status': 'available' if default else 'No valid two-sided quote' if views else 'Spread unavailable',
        })
    return {'season': season, 'week': selected_week, 'weeks': weeks, 'as_of': now.isoformat(),
            'games': output, 'issues': issues}


def research_for_team(code, season, week, coverage, injuries, depth):
    name = TEAM_NAMES.get(code, code)
    nickname = name.split()[-1]  # Official injury page uses unique NFL team nicknames.
    coverage_rows = [r for r in coverage.rows if r['team_name'] == name] if coverage else []
    report_matches = injuries is not None and injuries.context.get('season') == season and injuries.context.get('week') == week
    injury_rows = [r for r in injuries.rows if r['team_name'] == nickname] if report_matches else []
    reported = report_matches and nickname in injuries.context.get('reported_teams', [])
    depth_rows = [r for r in depth.rows if canonical(r.get('team')) == code] if depth else []
    depth_rows.sort(key=lambda r: (r.get('pos_grp', ''), r.get('pos_slot', '').zfill(3), r.get('pos_rank', '').zfill(3), r.get('player_name', '')))
    return {
        'coverage': coverage_rows[0] if len(coverage_rows) == 1 else None,
        'coverage_note': 'Published current table; statistical cutoff is unspecified.',
        'injuries': injury_rows,
        'injury_note': 'Blank game status does not mean healthy.' if reported else 'No matching injury report for this team, season and week.',
        'injuries_available': bool(reported),
        'depth': depth_rows,
        'depth_date': depth.context.get('team_snapshot_dates', {}).get(code) if depth else None,
    }
