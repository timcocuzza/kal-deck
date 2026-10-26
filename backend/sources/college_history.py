"""Validated D-I score history, with separately cached archives and current finals."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from urllib.parse import urlencode

from .common import SourceData, SourceError
from .college import BASE as RELEASES, read_table, REQUIRED
from .college_schedule import BASE as SCOREBOARD, parse_week
from ..college import parse_time

START = 2014
PHASES = {'regular', 'postseason', 'spring_regular', 'spring_postseason'}


def normalize(rows, year, *, now=None):
    now = now or datetime.now(timezone.utc)
    games, teams, seen, days = [], {}, set(), set()
    try:
        for row in rows:
            if str(row['season']) != str(year):
                raise SourceError('College rating history returned a different season.')
            if not {row[s + '_division'] for s in ('home', 'away')} <= {'fbs', 'fcs'}:
                continue
            gid = row['game_id']
            if not gid.isdigit() or gid in seen:
                raise SourceError('College rating history has a duplicate or invalid game ID.')
            seen.add(gid)
            if row['home_id'] == row['away_id'] or row['season_type'] not in PHASES:
                raise SourceError('College rating game identity/phase requires review.')
            for side in ('home', 'away'):
                tid, division, name = (row[side + key] for key in ('_id', '_division', '_team'))
                if not tid.isdigit() or not name or (tid in teams and teams[tid]['division'] != division):
                    raise SourceError('College season membership is missing or conflicting.')
                teams[tid] = {'id': tid, 'name': name, 'division': division}
            if row['completed'] not in ('true', 'false') or row['neutral_site'] not in ('true', 'false'):
                raise SourceError('College result has unknown completion or venue flags.')
            stamp = parse_time(row['start_date'])
            if stamp.year not in (year, year + 1) or not row['week'].isdigit() or not 0 <= int(row['week']) <= 30:
                raise SourceError('College result has an invalid date or week.')
            completed = row['completed'] == 'true'
            status = row.get('status', '')
            canceled = status in ('STATUS_CANCELED', 'STATUS_CANCELLED')
            if completed and (canceled or status not in ('', 'STATUS_FINAL', 'STATUS_FINAL_OVERTIME')):
                raise SourceError('College final status conflicts with completion.')
            if completed and stamp >= now:
                raise SourceError('College final was supplied before kickoff.')
            points = []
            for side in ('home', 'away'):
                value = row.get(side + '_points', '')
                if completed and (not isinstance(value, str) or not value.isdigit()):
                    raise SourceError('College final is missing a valid score.')
                points.append(int(value) if completed else None)
                if completed:
                    key = row[side + '_id'], stamp.date().isoformat()
                    if key in days:
                        raise SourceError('College team has multiple results on one date.')
                    days.add(key)
            neutral = row['neutral_site'] == 'true'
            correction = False
            if gid == '400795729':
                if (year, row['home_id'], row['away_id'], points, stamp.date().isoformat()) != (2015, '2571', '2449', [7, 28], '2015-10-03'):
                    raise SourceError('Reviewed college venue correction no longer matches its game.')
                correction, neutral = neutral, False
            games.append({'id': gid, 'season': year, 'week': int(row['week']), 'kickoff': stamp.isoformat(),
                          'day': stamp.date().isoformat(), 'home': row['home_id'], 'away': row['away_id'],
                          'home_name': row['home_team'], 'away_name': row['away_team'],
                          'home_div': row['home_division'], 'away_div': row['away_division'],
                          'home_score': points[0], 'away_score': points[1], 'neutral': neutral,
                          'phase': row['season_type'], 'completed': completed, 'canceled': canceled,
                          'status': status, 'venue_corrected': correction,
                          'neutral_labels_reversed': row.get('neutral_labels_reversed', False)})
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, SourceError):
            raise
        raise SourceError('Malformed college rating history; previous snapshot retained.') from error
    if not games or not any(t['division'] == 'fbs' for t in teams.values()):
        raise SourceError('College rating history has no usable Division I schedule.')
    return games, teams


def live_schedule(season, baseline, fetch, now):
    membership = {r[s + '_id']: r[s + '_division'] for r in baseline for s in ('home', 'away')}
    originals = {r['game_id']: r for r in baseline}
    weeks = range(1, max(15, max(int(r['week']) for r in baseline if r['season_type'] == 'regular')) + 1)
    plan = [(2, week, group) for week in weeks for group in (80, 81)]
    # Postseason feeds are queried after the regular-season calendar reaches
    # December.
    if now >= datetime(season, 12, 1, tzinfo=timezone.utc):
        plan += [(3, week, group) for week in range(1, 7) for group in (80, 81)]
    def load(item):
        phase, week, group = item
        url = SCOREBOARD + '?' + urlencode({'dates': season, 'week': week, 'seasontype': phase, 'groups': group, 'limit': 500})
        resource = fetch(url)
        try:
            data = json.loads(resource.body)
        except (ValueError, UnicodeError) as error:
            raise SourceError('College current finals returned unreadable JSON.') from error
        if not isinstance(data, dict) or not isinstance(data.get('events'), list):
            raise SourceError('College current finals have no event list.')
        # Empty unused future/postseason weeks have no season metadata. Baseline
        # reconciliation below still rejects omission of any known D-I game.
        rows = [] if not data['events'] else parse_week(data, season, week, originals, membership,
                                                       require_fbs=False, season_type=phase, allow_neutral_swap=True)
        return rows, {'url': url, 'fetched_at': resource.fetched_at}
    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(load, plan))
    merged = {}
    for rows, _ in pages:
        for row in rows:
            if not {row[s + '_division'] for s in ('home', 'away')} <= {'fbs', 'fcs'}:
                continue
            original = originals.get(row['game_id'])
            if original and original['completed'] == 'true' and row['completed'] != 'true':
                raise SourceError('Current college feed lost a previously completed result.')
            prior = merged.get(row['game_id'])
            if prior and any(prior[k] != row[k] for k in ('home_id', 'away_id', 'start_date', 'completed', 'home_points', 'away_points', 'neutral_site', 'season_type', 'week')):
                raise SourceError('College result changed between feed pages; retry refresh.')
            merged[row['game_id']] = row
    expected = {r['game_id'] for r in baseline if {r[s + '_division'] for s in ('home', 'away')} <= {'fbs', 'fcs'}}
    if expected - merged.keys():
        raise SourceError(f'Current college feeds omitted {len(expected - merged.keys())} baseline D-I games; previous history retained.')
    return list(merged.values()), [resource for _, resource in pages]


def load_history(season, fetch, store, *, now=None):
    now = now or datetime.now(timezone.utc)
    current = now.year if now.month >= 7 else now.year - 1
    if not START <= season <= current:
        raise SourceError(f'College strength history supports {START} through {current}.')
    sources, warnings, all_games, rosters = [], [], [], {}
    def archive(year):
        key = f'cfb_rating_archive:{year}'
        saved = store.read(key) if year < current else None
        if saved and now - parse_time(saved.fetched_at) < timedelta(days=7):
            return year, saved, True
        url = f'{RELEASES}/cfb_schedules/cfb_schedules_{year}.csv.gz'
        resource = fetch(url)
        rows = read_table(resource.body, True, REQUIRED['schedule'] | {'game_id', 'home_points', 'away_points'})
        normalize(rows, year, now=now)
        data = SourceData(rows, url, resource.fetched_at, resource.last_modified,
                          context={'sha256': hashlib.sha256(resource.body).hexdigest()})
        if year < current:
            prior = store.read(key)
            if prior and {r['game_id'] for r in prior.rows} - {r['game_id'] for r in rows}:
                raise SourceError('Historical college archive lost previously saved game IDs.')
            store.save(key, data)
        return year, data, False
    with ThreadPoolExecutor(max_workers=4) as pool:
        archives = list(pool.map(archive, range(START, season + 1)))
    for year, data, cached in archives:
        rows = data.rows
        sources.append({'dataset': str(year), 'url': data.url, 'fetched_at': data.fetched_at,
                        'source_updated_at': data.source_updated_at, 'cached': cached, **data.context})
        if year == current:
            rows, live_resources = live_schedule(year, rows, fetch, now)
            sources.extend({'dataset': 'Current finals', **r} for r in live_resources)
        games, teams = normalize(rows, year, now=now)
        if year < current and any(not g['completed'] and not g['canceled'] for g in games):
            raise SourceError('Historical college season has unresolved results.')
        all_games.extend(games)
        rosters[str(year)] = teams
    ids = [g['id'] for g in all_games]
    if len(ids) != len(set(ids)):
        raise SourceError('College history repeats game IDs across seasons.')
    previous = store.read(f'cfb_strength:{season}')
    if previous and {g['id'] for g in previous.rows[0]['games']} - set(ids):
        raise SourceError('College rating refresh lost previously saved game IDs.')
    current_finals = {g['id'] for g in all_games if g['completed']}
    if previous and {g['id'] for g in previous.rows[0]['games'] if g['completed']} - current_finals:
        raise SourceError('College rating refresh lost previously saved final results.')
    finals = sorted((g for g in all_games if g['completed']), key=lambda g: (g['day'], g['id']))
    if [g['season'] for g in finals] != sorted(g['season'] for g in finals):
        raise SourceError('College seasons overlap in calendar order; regression requires review.')
    warnings += ['Performance rating, not AP ranking or a calibrated spread/cover probability.',
                 'Season membership follows the bulk source, including transitional programs. Historical completeness is not independently certified.',
                 'Final margins include overtime. Historical rows may rely on completed flags without a named final status.',
                 'Historical archives are cached for seven days; current FBS and FCS finals refresh each time.']
    corrected = [g['id'] for g in all_games if g['venue_corrected']]
    if corrected:
        warnings.append('Reviewed venue correction applied to 2015 North Dakota State at South Dakota State (400795729).')
    neutral_swaps = [g['id'] for g in all_games if g['neutral_labels_reversed']]
    if neutral_swaps:
        warnings.append(f'{len(neutral_swaps)} neutral-site home/away label reversals reconciled by exact team, kickoff and final-score agreement.')
    return SourceData([{'games': all_games, 'rosters': rosters, 'version': 1}], sources[-1]['url'],
                      max(r['fetched_at'] for r in sources), context={'season': season, 'start_season': START,
                      'games': len(all_games), 'finals': len(finals), 'resources': sources, 'venue_corrections': corrected,
                      'neutral_label_reversals': neutral_swaps}, warnings=warnings)
