"""Public game and team identities used to verify market-to-schedule matches."""

from datetime import datetime
from urllib.parse import urlencode
from uuid import UUID

from .common import SourceData, SourceError, fetch_public
from .kalshi import BASE, _json_resource


def uuid_valid(value):
    try:
        UUID(value)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def timestamp(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date if date.tzinfo is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def _pages(path, params, field, fetch):
    initial_url = BASE + path + '?' + urlencode(params)
    cursor, cursors, rows, ids = '', set(), [], set()
    while True:
        url = initial_url + ('&' + urlencode({'cursor': cursor}) if cursor else '')
        resource, data = _json_resource(url, fetch)
        page = data.get(field)
        if not isinstance(page, list):
            raise SourceError('Kalshi identity list is missing or changed format.')
        for row in page:
            if not isinstance(row, dict) or not uuid_valid(row.get('id')) or row['id'] in ids:
                raise SourceError('Kalshi identity record has a missing or duplicate ID.')
            ids.add(row['id'])
            rows.append(row)
        cursor = data.get('cursor', '')
        if not isinstance(cursor, str) or cursor in cursors:
            raise SourceError('Kalshi identity pagination is incomplete.')
        if not cursor:
            break
        cursors.add(cursor)
    return SourceData(rows, initial_url, resource.fetched_at)


def load_teams(fetch=fetch_public):
    data = _pages('/structured_targets', {'type': 'football_team', 'competition': 'NFL', 'page_size': 100},
                  'structured_targets', fetch)
    selected = []
    for team in data.rows:
        details = team.get('details')
        if (team.get('name') == 'Retires / No Team' and isinstance(details, dict)
                and details.get('league') == 'NFL' and not details.get('abbreviation')):
            data.warnings.append('Kalshi’s Retires / No Team placeholder is excluded from game matching.')
            continue
        if (team.get('type') != 'football_team' or not isinstance(details, dict)
                or details.get('league') != 'NFL' or not details.get('abbreviation') or not team.get('name')):
            raise SourceError('Kalshi returned an incomplete or unexpected NFL team identity.')
        selected.append(team)
    data.rows = selected
    if not data.rows:
        raise SourceError('Kalshi supplied no NFL team identities.')
    data.context = {'league': 'NFL'}
    return data


def load_players(fetch=fetch_public):
    data = _pages('/structured_targets', {'type': 'football_player', 'competition': 'NFL', 'page_size': 2000},
                  'structured_targets', fetch)
    for player in data.rows:
        details = player.get('details')
        if (player.get('type') != 'football_player' or not player.get('name')
                or not isinstance(details, dict) or details.get('league') != 'NFL'):
            raise SourceError('Kalshi returned an incomplete or unexpected NFL player identity.')
    if not data.rows:
        raise SourceError('Kalshi supplied no NFL player identities.')
    data.context = {'league': 'NFL'}
    return data


def load_games(season, event_tickers, fetch=fetch_public, *, league='NFL'):
    # Resolve the exact cached events. Broad competition queries can return empty
    # even when the corresponding per-event milestone is available.
    from .common import utc_now
    rows = {}
    data = SourceData([], BASE + '/milestones', utc_now())
    events = sorted(set(event_tickers))
    for event in events:
        page = _pages('/milestones', {'limit': 100, 'related_event_ticker': event}, 'milestones', fetch)
        data.fetched_at = page.fetched_at
        if not page.rows:
            data.warnings.append(f'No game identity supplied for {event}; matching requires review.')
        for row in page.rows:
            if row['id'] in rows and rows[row['id']] != row:
                raise SourceError('Kalshi game identity changed during refresh; retry the refresh.')
            rows[row['id']] = row
    data.rows = list(rows.values())
    selected = []
    for game in data.rows:
        details = game.get('details')
        if not isinstance(details, dict) or not isinstance(details.get('season'), dict):
            raise SourceError('Kalshi game season metadata is missing.')
        phase = details['season']
        if str(phase.get('year')) != str(season) or phase.get('type') not in (('REG', 'PST') if league == 'NCAAFB' else ('REG',)):
            continue
        if (game.get('type') != 'football_game' or details.get('league') != league
                or (league == 'NCAAFB' and details.get('division') not in
                    (('FBS', 'FCS', 'D2', None) if phase['type'] == 'PST' else ('FBS', 'FCS', 'D2')))
                or not timestamp(game.get('start_date'))
                or not all(uuid_valid(details.get(key)) for key in ('home_team_id', 'away_team_id'))
                or details['home_team_id'] == details['away_team_id']
                or (phase['type'] == 'REG' and (type(phase.get('week')) is not int
                    or not 1 <= phase['week'] <= (30 if league == 'NCAAFB' else 18)))):
            raise SourceError('Kalshi supplied incomplete or conflicting game identity data.')
        for key in ('primary_event_tickers', 'related_event_tickers'):
            if not isinstance(game.get(key), list) or any(not isinstance(t, str) for t in game[key]):
                raise SourceError('Kalshi game event links are missing or malformed.')
        selected.append(game)
    data.rows = selected
    data.context = {'season': season, 'phase': 'REG/PST' if league == 'NCAAFB' else 'REG', 'requested_events': events}
    return data
