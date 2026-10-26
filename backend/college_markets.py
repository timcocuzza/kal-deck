"""Strict college identity joins; no ticker-derived or fuzzy team matching."""
from collections import defaultdict
from decimal import InvalidOperation
import unicodedata

from .college import parse_time
from .matchups import contract_view
from .sources.common import SourceError
from .sources.kalshi import select_default_spread
from .sources.kalshi_metadata import uuid_valid

# Verified against both providers on October 24, 2026. Alias approval is bound to
# exact IDs, full names and abbreviation; changed metadata fails closed.
TEAM_ALIASES = {
    '0ac94a1a-15e0-4201-991e-af57de732f98': ('2433', 'Louisiana-Monroe Warhawks', 'UL Monroe Warhawks', 'ULM'),
    '7d548f70-b3f7-480b-9ee9-cd6b600bbffc': ('2026', 'Appalachian State Mountaineers', 'App State Mountaineers', 'APP'),
    'adf4bbc4-05b7-45fa-9916-da416f2ea481': ('23', 'San Jose State Spartans', 'San José State Spartans', 'SJSU'),
    'f17cc58a-4b13-4c14-b420-c3b7dd172fe4': ('2390', 'Miami (FL) Hurricanes', 'Miami Hurricanes', 'MIA'),
}


def name_key(value):
    return ' '.join(unicodedata.normalize('NFC', value).casefold().split()) if isinstance(value, str) else ''


def college_team_links(schedule, targets):
    teams = {}
    for game in schedule:
        if not game.get('schedule_verified'):
            continue
        for side in ('home', 'away'):
            tid = game[side + '_id']
            if game[side + '_division'] not in ('fbs', 'fcs'):
                continue
            team = teams.setdefault(tid, {'full': set(), 'short': set(), 'abbreviations': set(), 'division': game[side + '_division']})
            team['full'].add(name_key(game.get(side + '_full_name')))
            team['short'].update(name_key(game.get(side + suffix)) for suffix in ('_team', '_short_name'))
            team['abbreviations'].add(name_key(game.get(side + '_abbreviation')))
    candidates, issues, by_espn = {}, [], defaultdict(list)
    for target in targets:
        details = target.get('details', {})
        if (not uuid_valid(target.get('id')) or target.get('type') != 'football_team'
                or details.get('league') != 'NCAAFB'):
            issues.append({'reason': 'Invalid college team target; matching requires review.'})
            continue
        full = name_key(details.get('team_name'))
        short = {name_key(target.get('name')), name_key(details.get('market'))} - {''}
        abbreviation = name_key(details.get('abbreviation'))
        matched = [tid for tid, team in teams.items()
                   if details.get('division', '').lower() == team['division']
                   and ((full and full in team['full']) or
                        (abbreviation and abbreviation in team['abbreviations'] and short.intersection(team['short'])))]
        alias = TEAM_ALIASES.get(target['id'])
        if not matched and alias:
            tid, kalshi_name, espn_name, code = alias
            team = teams.get(tid)
            if (team and full == name_key(kalshi_name) and name_key(espn_name) in team['full']
                    and abbreviation == name_key(code) and abbreviation in team['abbreviations']
                    and details.get('division', '').lower() == team['division']):
                matched = [tid]
        conflicting_codes = {tid for tid, team in teams.items() if abbreviation and abbreviation in team['abbreviations']}
        if len(matched) == 1 and conflicting_codes and matched[0] not in conflicting_codes:
            matched = []
        if len(matched) != 1:
            # Many FCS targets have no game against an FBS team this season.
            if details.get('division') == 'FBS' or matched:
                issues.append({'reason': f"No unique exact team match for {target.get('name', 'unknown team')}."})
            continue
        by_espn[matched[0]].append(target['id'])
        if target['id'] in candidates:
            raise SourceError('Duplicate college team target ID.')
        candidates[target['id']] = matched[0]
    ambiguous = {tid for tid, ids in by_espn.items() if len(ids) != 1}
    for tid in ambiguous:
        issues.append({'reason': f'Multiple Kalshi identities match college team {tid}; quotes withheld.'})
    return {key: tid for key, tid in candidates.items() if tid not in ambiguous}, issues


def attach_college_markets(report, schedule, market_bundle, season):
    links, issues = college_team_links(schedule, market_bundle.get('targets', []))
    targets = {t['id']: t for t in market_bundle.get('targets', []) if t.get('id') in links}
    event_links, grouped, matched = defaultdict(list), defaultdict(list), defaultdict(list)
    for milestone in market_bundle.get('milestones', []):
        for event in set(milestone.get('related_event_tickers', []) + milestone.get('primary_event_tickers', [])):
            event_links[event].append(milestone)
    for market in market_bundle.get('markets', []):
        grouped[market['event_ticker']].append(market)
    for event, contracts in grouped.items():
        milestones = event_links[event]
        if len(milestones) != 1:
            issues.append({'event': event, 'reason': 'Missing or ambiguous college game identity.'})
            continue
        milestone = milestones[0]
        details = milestone.get('details', {})
        phase = details.get('season', {})
        home, away = links.get(details.get('home_team_id')), links.get(details.get('away_team_id'))
        if (not home or not away or home == away or milestone.get('type') != 'football_game'
                or details.get('league') != 'NCAAFB' or details.get('division') not in ('FBS', None)
                or str(phase.get('year')) != str(season) or phase.get('type') not in ('REG', 'PST')
                or details.get('status') != 'scheduled'):
            issues.append({'event': event, 'reason': 'College season or participant identities could not be verified.'})
            continue
        # Kalshi uses postseason rounds, ESPN uses weeks. Match the season phase,
        # exact participants and kickoff, never translate a round into a week.
        try:
            games = [g for g in schedule if g['home_id'] == home and g['away_id'] == away
                     and g['fbs_participant'] == 'true'
                     and g['season_type'] == ('postseason' if phase['type'] == 'PST' else 'regular')
                     and (phase['type'] == 'PST' or g['week'] == str(phase.get('week')))
                     and parse_time(g['start_date']) == parse_time(milestone.get('start_date'))]
            verified = (len(games) == 1 and games[0].get('schedule_verified')
                        and games[0].get('participants_confirmed') and games[0]['start_time_tbd'] == 'false'
                        and games[0].get('status') == 'STATUS_SCHEDULED'
                        and parse_time(games[0]['start_date']) == parse_time(milestone.get('start_date')))
        except SourceError:
            verified = False
        if not verified:
            issues.append({'event': event, 'reason': 'Current college teams, week or confirmed kickoff disagree; quotes withheld.'})
            continue
        views, eligible = [], []
        for market in contracts:
            try:
                if market.get('status') not in ('active', 'open'):
                    raise ValueError('College contract is not open.')
                view = contract_view(market, milestone, targets, league='NCAAFB')
                view['team_id'] = links[market['custom_strike']['football_team']]
                view['rules_secondary'] = market.get('rules_secondary', '')
                views.append(view)
                eligible.append(market)
            except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as error:
                issues.append({'event': event, 'market': market.get('ticker'), 'reason': str(error) or 'Malformed college contract.'})
        matched[games[0]['game_id']].append((views, eligible))
    for game in report['games']:
        records = matched[game['game_id']]
        views, eligible = records[0] if len(records) == 1 else ([], [])
        if len(records) > 1:
            issues.append({'reason': f"Multiple college spread events match {game['game_id']}; quotes withheld."})
        default = select_default_spread(eligible)
        game.update(markets=sorted(views, key=lambda v: (v['team'], v['spread'])),
                    default_market_ticker=default['ticker'] if default else None,
                    spread_status='Available' if default else 'No valid two-sided quote' if views else 'Spread unavailable')
    report['issues'] = issues
    return report
