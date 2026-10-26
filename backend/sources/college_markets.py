"""College contracts and their public identities saved as one coherent snapshot."""
from .common import SourceData, SourceError
from .college_market_fetch import CollegeMarketFetch
from .kalshi import BASE, load_markets
from .kalshi_metadata import _pages, load_games

SERIES = 'KXNCAAFSPREAD'


def load_college_markets(season, fetch, store=None):
    if store is not None:
        fetch = CollegeMarketFetch(fetch, store)
    markets = load_markets(SERIES, fetch)
    teams = _pages('/structured_targets', {'type': 'football_team', 'competition': 'NCAAFB', 'page_size': 1000},
                   'structured_targets', fetch)
    selected = []
    for target in teams.rows:
        details = target.get('details')
        if target.get('type') != 'football_team' or not isinstance(details, dict) or details.get('league') != 'NCAAFB':
            raise SourceError('Kalshi returned an unexpected college team identity.')
        if details.get('division') not in ('FBS', 'FCS'):
            continue
        if not target.get('name') or not details.get('abbreviation') or not details.get('team_name'):
            raise SourceError('Kalshi returned incomplete college team names.')
        selected.append(target)
    if not selected:
        raise SourceError('Kalshi supplied no college team identities.')
    events = sorted({market['event_ticker'] for market in markets.rows})
    if len(events) > 500:
        raise SourceError('Unexpected college event count; refresh requires review.')
    def fetch_event(event):
        return load_games(season, [event], fetch, league='NCAAFB')
    # Sequential, paced cache misses avoid a burst of requests for every event.
    pages = [fetch_event(event) for event in events]
    milestones = {}
    for page in pages:
        for row in page.rows:
            if row['id'] in milestones and milestones[row['id']] != row:
                raise SourceError('College game identity changed during refresh; retry.')
            milestones[row['id']] = row
    # The college spread series also contains FCS-only games. Their explicit
    # division metadata scopes them out; they are not a malformed FBS refresh.
    excluded = {event for row in milestones.values() if row['details'].get('division') not in ('FBS', None)
                for event in row['primary_event_tickers'] + row['related_event_tickers']}
    # Archived postseason milestones may omit division/week. The report still
    # requires an exact match to an ESPN game with an FBS participant.
    kept = [row for row in milestones.values() if row['details'].get('division') in ('FBS', None)]
    conflicts = excluded.intersection(event for row in kept for event in row['primary_event_tickers'] + row['related_event_tickers'])
    if conflicts:
        raise SourceError('College events have conflicting FBS/non-FBS classifications.')
    return SourceData([{'markets': [m for m in markets.rows if m['event_ticker'] not in excluded], 'milestones': kept, 'targets': selected}],
                      markets.url, markets.fetched_at,
                      context={'season': season, 'series': SERIES, 'events': len(events), 'excluded_non_fbs_events': len(set(events) & excluded),
                               'identities_fetched_at': teams.fetched_at,
                               'milestones_fetched_at': {event: page.fetched_at for event, page in zip(events, pages)},
                               'team_url': teams.url, 'game_url': BASE + '/milestones'},
                      warnings=[warning for page in pages for warning in page.warnings])
