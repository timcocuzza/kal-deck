"""Reconcile cached ESPN team schedules against bulk college history.

This is a targeted spot check, not independent NCAA membership certification.
Cache names and exact public URLs are recorded in the output artifact.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path


CASES = [(2012, 149), (2014, 2449), (2015, 2449), (2018, 2453), (2018, 2261), (2023, 338), (2025, 149)]


def audit(cache):
    results = []
    for year, team in CASES:
        with gzip.open(cache / f'cfb_schedules_{year}.csv.gz', 'rt') as stream:
            bulk = {row['game_id']: row for row in csv.DictReader(stream)}
        membership = {row[s + '_id']: row[s + '_division'] for row in bulk.values() for s in ('home', 'away')}
        events, sources, metadata_notices = {}, [], []
        for phase in (2, 3):
            path = cache / f'elo-team-{team}-{year}-{phase}.json'
            if year == 2012:
                if phase == 3:
                    continue
                path = cache / 'elo-montana-2012.json'
            body = path.read_bytes()
            source = json.loads(body)
            sources.append({'url': f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team}/schedule?season={year}&seasontype={phase}',
                            'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)})
            if str(source.get('season', {}).get('year')) != str(year):
                metadata_notices.append('Top-level season metadata is current, not requested historical season; validate each event season instead.')
            if str(source['team']['id']) != str(team):
                raise ValueError('Requested team identity disagrees')
            for event in source['events']:
                if event['season']['year'] != year:
                    raise ValueError('Wrong event season')
                if event['id'] in events and events[event['id']] != event:
                    raise ValueError('Conflicting duplicate ESPN event')
                events[event['id']] = event
        matches, missing, conflicts, omitted = [], [], [], Counter()
        for gid, event in events.items():
            if len(event['competitions']) != 1:
                raise ValueError('Ambiguous ESPN competition')
            competition = event['competitions'][0]
            sides = {r['homeAway']: r for r in competition['competitors']}
            if set(sides) != {'home', 'away'} or competition['id'] != gid:
                raise ValueError('Invalid ESPN participant identities')
            ids = {str(c['team']['id']) for c in sides.values()}
            if str(team) not in ids or any(str(c['id']) != str(c['team']['id']) for c in sides.values()):
                raise ValueError('ESPN participant IDs disagree')
            if not competition['status']['type']['completed']:
                omitted['nonfinal'] += 1
                continue
            if any(membership.get(tid) not in ('fbs', 'fcs') for tid in ids):
                omitted['outside_d1_or_not_classified_in_bulk'] += 1
                continue
            row = bulk.get(gid)
            if not row:
                missing.append({'game_id': gid, 'name': event['name'], 'date': event['date']})
                continue
            actual = {str(c['id']): int(c['score']['displayValue']) for c in sides.values()}
            expected = {row[s + '_id']: int(row[s + '_points']) for s in ('home', 'away')}
            if actual != expected or competition['neutralSite'] != (row['neutral_site'] == 'true'):
                conflicts.append({'game_id': gid, 'reason': 'Score, identity or neutral-site discrepancy'})
            elif ids != {row['home_id'], row['away_id']}:
                conflicts.append({'game_id': gid, 'reason': 'Participant discrepancy'})
            else:
                matches.append(gid)
        bulk_ids = {g['game_id'] for g in bulk.values()
                    if str(team) in (g['home_id'], g['away_id']) and g['completed'] == 'true'
                    and {g['home_division'], g['away_division']} <= {'fbs', 'fcs'}}
        results.append({'season': year, 'team_id': str(team), 'team_name': source['team']['displayName'],
                        'sources': sources, 'espn_total_events': len(events), 'matched_d1_results': len(matches),
                        'missing_from_bulk': missing, 'bulk_d1_ids_absent_from_espn': sorted(bulk_ids - events.keys()),
                        'conflicts': conflicts, 'omitted': dict(omitted), 'metadata_notices': sorted(set(metadata_notices))})
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': results,
            'scope': 'Seven targeted team-season checks, not an exhaustive completeness proof. Providers may share upstream data.',
            'finding': '2012 Montana has nine known missing bulk games; later checked cases must be assessed individually.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = audit(args.cache)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps([{k: v for k, v in row.items() if k not in ('sources', 'metadata_notices')}
                      for row in result['checks']], indent=2))
