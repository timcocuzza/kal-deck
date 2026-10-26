"""Free college season tables, validated and saved together as one snapshot."""
import csv
import gzip
import hashlib
import io
import zlib
from fractions import Fraction

from .common import SourceData, SourceError
from ..college import index_rows, parse_time

BASE = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download'
DATASETS = {
    'schedule': ('cfb_schedules', 'cfb_schedules_{season}.csv.gz', 'game_id'),
    'team_box': ('espn_cfb_team_box', 'team_box_{season}.csv', 'team_id'),
    'adv_team': ('espn_cfb_adv_team', 'adv_team_{season}.csv', 'pos_team_id'),
    'adv_defensive': ('espn_cfb_adv_defensive', 'adv_defensive_{season}.csv', 'def_pos_team_id'),
    'adv_situational': ('espn_cfb_adv_situational', 'adv_situational_{season}.csv', 'pos_team_id'),
}
REQUIRED = {
    'schedule': {'season', 'week', 'season_type', 'start_date', 'start_time_tbd', 'completed',
                 'neutral_site', 'home_id', 'away_id', 'home_team', 'away_team', 'home_division',
                 'away_division', 'fbs_game', 'fbs_participant'},
    'team_box': {'netPassingYards', 'completionAttempts', 'rushingYards', 'rushingAttempts', 'interceptions'},
    'adv_team': {'EPA_passing_per_play', 'EPA_rushing_per_play'},
    'adv_defensive': {'sacks'},
    'adv_situational': {'EPA_success_rush_rate'},
}


def read_table(body, compressed, required):
    try:
        if compressed:
            body = gzip.decompress(body)
        if len(body) > 25_000_000:
            raise SourceError('College source exceeded the supported table size.')
        reader = csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
        if not required.issubset(reader.fieldnames or []):
            raise SourceError('College source columns changed; previous snapshot retained.')
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise SourceError('College source contains a truncated or malformed row.')
        return rows
    except (UnicodeError, csv.Error, gzip.BadGzipFile, EOFError, zlib.error) as error:
        raise SourceError('College source did not return readable CSV data.') from error


def validate_bundle(bundle, season):
    schedule = bundle['schedule']
    if not schedule:
        raise SourceError('No college schedule was supplied.')
    games = {}
    divisions = {}
    for row in schedule:
        if row['season'] != str(season):
            raise SourceError('College schedule returned a different season.')
        gid = row['game_id']
        if not gid.isdigit() or gid in games:
            raise SourceError('College schedule has an invalid or duplicate game ID.')
        parse_time(row['start_date'])
        if not row['week'].isdigit() or not 0 <= int(row['week']) <= 30:
            raise SourceError('College schedule has an invalid week.')
        if any(row[key] not in ('true', 'false') for key in
               ('start_time_tbd', 'completed', 'neutral_site', 'fbs_game', 'fbs_participant')):
            raise SourceError('College schedule has an unknown status flag.')
        for side in ('home', 'away'):
            tid = row[side + '_id']
            if not tid.isdigit() or not row[side + '_team'] or row['home_id'] == row['away_id']:
                raise SourceError('College schedule has invalid team identities.')
            division = row[side + '_division']
            if tid in divisions and divisions[tid] != division:
                raise SourceError('College schedule has conflicting team classifications.')
            divisions[tid] = division
        fbs_count = sum(row[s + '_division'] == 'fbs' for s in ('home', 'away'))
        if fbs_count and any(row[s + '_division'] not in ('fbs', 'fcs') for s in ('home', 'away')):
            raise SourceError('An FBS opponent has an unknown division; classification needs review.')
        if (row['fbs_game'] == 'true') != (fbs_count == 2) or (row['fbs_participant'] == 'true') != (fbs_count > 0):
            raise SourceError('College schedule has conflicting FBS flags.')
        games[gid] = row
    if 'fbs' not in divisions.values():
        raise SourceError('College schedule contains no FBS teams.')
    missing = {}
    expected = {(g['game_id'], g[s + '_id']) for g in schedule
                if g['completed'] == 'true' and g['fbs_participant'] == 'true' for s in ('home', 'away')}
    for name, (_, _, team_key) in DATASETS.items():
        if name == 'schedule':
            continue
        rows = bundle[name]
        if expected and not rows:
            raise SourceError('College statistics are empty despite completed games; previous snapshot retained.')
        indexed = index_rows(rows, team_key)
        for (gid, tid), row in indexed.items():
            game = games.get(gid)
            if row['season'] != str(season) or not game or tid not in (game['home_id'], game['away_id']):
                raise SourceError('College statistics conflict with the schedule or season.')
            # Reject malformed numbers, but preserve explicit missing values for coverage reporting.
            numeric = REQUIRED[name] - {'completionAttempts'}
            for key in numeric:
                value = row[key]
                if value in ('', 'NA', 'NaN', 'nan'):
                    continue
                try:
                    number = Fraction(value)
                    if key in ('sacks', 'interceptions', 'rushingAttempts') and (number < 0 or number.denominator != 1):
                        raise ValueError()
                    if key == 'EPA_success_rush_rate' and not 0 <= number <= 1:
                        raise ValueError()
                except (ValueError, ZeroDivisionError) as error:
                    raise SourceError(f'College source has an invalid {key} value.') from error
            if name == 'team_box' and row['completionAttempts'] not in ('', 'NA', 'NaN', 'nan'):
                parts = row['completionAttempts'].split('/')
                if len(parts) != 2 or not all(p.isdigit() for p in parts) or int(parts[0]) > int(parts[1]):
                    raise SourceError('College source has invalid completions/attempts.')
        missing[name] = len(expected - indexed.keys())
    return missing


def load_college(season, fetch):
    bundle, resources = {}, []
    for name, (tag, filename, team_key) in DATASETS.items():
        url = f'{BASE}/{tag}/{filename.format(season=season)}'
        resource = fetch(url)
        required = REQUIRED[name] | {'game_id', 'season', team_key}
        bundle[name] = read_table(resource.body, filename.endswith('.gz'), required)
        resources.append({'dataset': name, 'url': url, 'fetched_at': resource.fetched_at,
                          'source_updated_at': resource.last_modified,
                          'sha256': hashlib.sha256(resource.body).hexdigest()})
    missing = validate_bundle(bundle, season)
    warnings = [f'{name}: {count} completed team-game rows missing.' for name, count in missing.items() if count]
    warnings.append('Published EPA is rounded and classifies scrambles as rushes. It differs from NFL dropback/designed-run EPA.')
    return SourceData(rows=[bundle], url=f'{BASE}/cfb_schedules/cfb_schedules_{season}.csv.gz',
                      fetched_at=resources[-1]['fetched_at'], context={'season': season, 'resources': resources},
                      warnings=warnings)
