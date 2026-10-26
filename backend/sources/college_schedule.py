"""Current ESPN schedules reconciled against the season's classified team IDs."""
from concurrent.futures import ThreadPoolExecutor
import json
from urllib.parse import urlencode

from .common import SourceData, SourceError
from ..college import parse_time

BASE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard'


def parse_week(data, season, week, baseline, membership, *, require_fbs=True, season_type=2, allow_neutral_swap=False):
    if (not isinstance(data, dict) or data.get('season', {}).get('year') != season
            or data.get('season', {}).get('type') != season_type or data.get('week', {}).get('number') != week
            or not isinstance(data.get('events'), list)):
        raise SourceError(f'College week {week}: season/week or event list could not be verified.')
    output, seen = [], set()
    try:
        for event in data['events']:
            gid = event['id']
            if not isinstance(gid, str) or not gid.isdigit() or gid in seen:
                raise SourceError('Current college schedule has an invalid or duplicate game ID.')
            seen.add(gid)
            if event['season']['year'] != season or event['season']['type'] != season_type or event['week']['number'] != week:
                raise SourceError('Current college event conflicts with the requested season/week.')
            if len(event['competitions']) != 1:
                raise SourceError('College event has ambiguous competitions.')
            competition = event['competitions'][0]
            if competition['id'] != gid or parse_time(competition['date']) != parse_time(event['date']):
                raise SourceError('College event and competition identities disagree.')
            if any(type(competition.get(key)) is not bool for key in ('timeValid', 'dateValid', 'neutralSite')):
                raise SourceError('College schedule is missing time-validity or venue flags.')
            status = competition['status']['type']
            if status != event['status']['type'] or type(status.get('completed')) is not bool:
                raise SourceError('College event status is missing or inconsistent.')
            if status.get('state') not in ('pre', 'in', 'post') or not isinstance(status.get('name'), str):
                raise SourceError('College event has an unknown status.')
            if status['completed'] and status['state'] != 'post':
                raise SourceError('College final status conflicts with game state.')
            teams = competition['competitors']
            if len(teams) != 2 or {t['homeAway'] for t in teams} != {'home', 'away'}:
                raise SourceError('College home/away assignments are ambiguous.')
            row = {'game_id': gid, 'season': str(season), 'week': str(week), 'season_type': 'regular' if season_type == 2 else 'postseason',
                   'start_date': event['date'], 'start_time_tbd': str(not (competition['timeValid'] and competition['dateValid'])).lower(),
                   'completed': str(status['completed']).lower(), 'neutral_site': str(competition['neutralSite']).lower(),
                   'status': status['name'], 'state': status['state'], 'schedule_verified': True,
                   'venue': competition.get('venue', {}).get('fullName', '')}
            for competitor in teams:
                side, team = competitor['homeAway'], competitor['team']
                tid = team['id']
                if tid != competitor['id'] or not isinstance(tid, str):
                    raise SourceError('College participant IDs disagree.')
                placeholder = tid in ('-1', '-2') and team.get('displayName') == 'TBD'
                placeholder = placeholder or (tid in ('112350', '112351') and team.get('displayName') == 'TBA'
                                               and team.get('location') == 'TBA' and team.get('abbreviation') == 'TBA')
                if placeholder and (status['completed'] or status['state'] != 'pre'):
                    raise SourceError('A started college game still has unconfirmed participants.')
                if not placeholder and (not tid.isdigit() or tid not in membership):
                    raise SourceError('An unclassified college participant requires membership review.')
                if not isinstance(team.get('displayName'), str) or not team['displayName']:
                    raise SourceError('College participant name is missing.')
                division = 'unknown' if placeholder else membership[tid]
                row.update({side + '_id': tid, side + '_division': division,
                            side + '_team': team.get('location') or team['displayName'],
                            side + '_full_name': team['displayName'],
                            side + '_abbreviation': team.get('abbreviation') or '',
                            side + '_short_name': team.get('shortDisplayName') or ''})
                score = competitor.get('score')
                if status['completed'] and (not isinstance(score, str) or not score.isdigit()):
                    raise SourceError('College final is missing a valid score.')
                row[side + '_points'] = score if status['completed'] else ''
            if row['home_id'] == row['away_id']:
                raise SourceError('College game assigns the same participant to both sides.')
            original = baseline.get(gid)
            changed = original and any(row[side + '_id'] != original[side + '_id'] for side in ('home', 'away'))
            resolved = changed and original['completed'] == 'false' and all(
                original[s + '_id'] == row[s + '_id'] or original[s + '_id'] in ('-1', '-2', '112350', '112351')
                for s in ('home', 'away'))
            if changed and not resolved:
                # Some neutral-site feeds reverse the nominal home/away labels.
                # Accept only the exact same teams, kickoff, and per-team final
                # scores, with both sources explicitly marking neutral venue.
                swap = (allow_neutral_swap and row['neutral_site'] == original['neutral_site'] == 'true'
                        and parse_time(row['start_date']) == parse_time(original['start_date'])
                        and row['completed'] == original['completed'] == 'true'
                        and all(row[a + '_id'] == original[b + '_id']
                                and row[a + '_points'] == original[b + '_points']
                                for a, b in [('home', 'away'), ('away', 'home')]))
                if not swap:
                    raise SourceError(f'Current college participants conflict with the saved schedule for game {gid}.')
                row['neutral_labels_reversed'] = True
            divisions = {row[s + '_division'] for s in ('home', 'away')}
            if require_fbs and 'fbs' not in divisions and 'unknown' not in divisions:
                raise SourceError('FBS scoreboard returned a game with no FBS participant.')
            row['fbs_participant'] = str('fbs' in divisions).lower()
            row['fbs_scoreboard'] = require_fbs
            row['fbs_game'] = str(divisions == {'fbs'}).lower()
            row['participants_confirmed'] = 'unknown' not in divisions
            output.append(row)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, SourceError):
            raise
        raise SourceError(f'College week {week}: malformed schedule data.') from error
    return output


def load_current_schedule(season, schedule, fetch):
    baseline = {g['game_id']: g for g in schedule if g['fbs_participant'] == 'true' and g['season_type'] in ('regular', 'postseason')}
    if not baseline:
        raise SourceError('Refresh college statistics/schedule before the current schedule.')
    membership = {g[s + '_id']: g[s + '_division'] for g in schedule for s in ('home', 'away')}
    # ESPN groups bowls and the CFP in postseason week 1. Query additional
    # weeks too, so a future calendar split does not silently omit later rounds.
    last_week = max(15, max((int(g['week']) for g in baseline.values() if g['season_type'] == 'regular'), default=15))
    weeks = [(2, week) for week in range(1, last_week + 1)] + [(3, week) for week in range(1, 7)]
    def load_week(period):
        phase, week = period
        url = BASE + '?' + urlencode({'dates': season, 'week': week, 'seasontype': phase, 'groups': 80, 'limit': 500})
        resource = fetch(url)
        try:
            data = json.loads(resource.body)
        except (ValueError, UnicodeError) as error:
            raise SourceError('Current college schedule returned unreadable JSON.') from error
        if not isinstance(data, dict) or not isinstance(data.get('events'), list):
            raise SourceError('Current college schedule has no event list.')
        # Unused postseason weeks can omit season/week metadata. Known games
        # are still required by the baseline completeness check below.
        rows = [] if not data['events'] else parse_week(data, season, week, baseline, membership,
                                                       season_type=phase, allow_neutral_swap=True)
        return rows, resource
    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(load_week, weeks))
    rows = [row for page, _ in pages for row in page]
    ids = [row['game_id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise SourceError('Current college schedule repeats a game across weeks.')
    missing = baseline.keys() - set(ids)
    if missing:
        raise SourceError(f'Current college schedule omitted {len(missing)} saved games; previous snapshot retained.')
    return SourceData(rows, BASE, max(resource.fetched_at for _, resource in pages),
                      context={'season': season, 'periods': weeks, 'baseline_games': len(baseline),
                               'resources': [{'dataset': f'{"Regular season" if phase == 2 else "Postseason"} week {w}', 'url': resource.url, 'fetched_at': resource.fetched_at}
                                             for (phase, w), (_, resource) in zip(weeks, pages)]},
                      warnings=['Current schedule reconciled against saved game IDs; membership still follows the bulk source.',
                                'Schedule updates do not supply missing game statistics.'])
