"""Verify cached public market evidence against the independently checked schedule.

Run from any directory after fetching the files listed in SOURCES. No app writes,
network calls, database access or trading. Reuses the app's pure quote functions.
"""
import ast
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
CACHE = Path('/tmp/deck-cfb-audit')
BASE = 'https://external-api.kalshi.com/trade-api/v2'
EVENT = 'KXNCAAFSPREAD-26OCT24BYUUCF'
SOURCES = {
    'event': BASE + '/events/' + EVENT,
    'milestone': BASE + '/milestones?limit=100&related_event_ticker=' + EVENT,
    'byu': BASE + '/structured_targets/155b8f85-a763-46c9-a6d2-82dfea5a7cdc',
    'ucf': BASE + '/structured_targets/12f48f09-feae-4074-9ff1-2e5bae9c33fe',
    'history': BASE + '/series/KXNCAAFSPREAD/markets/' + EVENT + '-BYU8/candlesticks?start_ts=1792253163&end_ts=1792857963&period_interval=60',
}

def iso(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def main():
    payloads = {}; sources = {}
    for name, url in SOURCES.items():
        path = CACHE / ('kalshi-' + name + '.json')
        raw = path.read_bytes(); payloads[name] = json.loads(raw)
        sources[name] = {'url': url, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                         'retrieved_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    source_path = ROOT / 'backend/sources/kalshi.py'
    tree = ast.parse(source_path.read_text())
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in ('quote_midpoint', 'select_default_spread', 'history_points')]
    assert len(funcs) == 3
    scope = {'Decimal': Decimal, 'InvalidOperation': InvalidOperation}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(source_path), 'exec'), scope)
    schedule = json.loads((OUT / 'schedule-feed-audit.json').read_text())['sample_matchup']
    milestone = payloads['milestone']['milestones'][0]
    details = milestone['details']
    targets = {name: payloads[name]['structured_target'] for name in ('byu', 'ucf')}
    checks = {
        'single_unpaginated_milestone': len(payloads['milestone']['milestones']) == 1 and not payloads['milestone']['cursor'],
        'event_series': payloads['event']['event']['series_ticker'] == 'KXNCAAFSPREAD',
        'event_linked_to_milestone': EVENT in milestone['related_event_tickers'],
        'league': details['league'] == 'NCAAFB' and details['division'] == 'FBS',
        'season_week': details['season'] == {'type': 'REG', 'week': 8, 'year': 2026},
        'valid_schedule_time': schedule['time_valid'] and schedule['date_valid'],
        'kickoff_matches': iso(milestone['start_date']) == iso(schedule['start_date']),
        'away_identity': details['away_team_id'] == targets['byu']['id'] and targets['byu']['name'] == 'BYU' and schedule['teams']['away']['id'] == '252',
        'home_identity': details['home_team_id'] == targets['ucf']['id'] and targets['ucf']['name'] == 'UCF' and schedule['teams']['home']['id'] == '2116',
        'team_types': all(t['type'] == 'football_team' and t['details']['league'] == 'NCAAFB' for t in targets.values()),
    }
    markets = payloads['event']['markets']
    selected = scope['select_default_spread'](markets)
    assert selected is not None
    checks['selected_contract_wording'] = selected['rules_primary'] == (
        'If BYU wins by more than 7.5 points in the BYU vs UCF college football game originally scheduled for Oct 24, 2026, then the market resolves to Yes.')
    checks['selected_threshold'] = selected['floor_strike'] == 7.5 and selected['event_ticker'] == EVENT
    history = payloads['history']
    checks['history_ticker_matches_selection'] = history['ticker'] == selected['ticker']
    points = scope['history_points'](history['candlesticks'])
    times = [p['timestamp'] for p in points]
    checks['unique_history_times'] = len(times) == len(set(times))
    checks['history_window'] = all(1792253163 <= t <= 1792857963 for t in times)
    missing_hours = sum(max(0, (b-a)//3600-1) for a,b in zip(times,times[1:]))
    output = {
        'checked_at': datetime.now(timezone.utc).isoformat(), 'sources': sources,
        'checks': checks, 'sample_match_verified': all(checks.values()),
        'identity_method': 'Explicit manually checked BYU/UCF alias-to-numeric-ID mapping; no general college crosswalk claimed.',
        'selection_method': 'Existing backend select_default_spread function: midpoint closest to 50%, then gap, volume and ticker.',
        'quote_function_source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'contracts_returned': len(markets),
        'contracts_with_valid_midpoints': sum(scope['quote_midpoint'](m) is not None for m in markets),
        'selected_contract': {k:selected.get(k) for k in ('ticker','title','status','floor_strike','yes_bid_dollars','yes_ask_dollars','no_ask_dollars','rules_primary','rules_secondary')},
        'selected_midpoint': float(scope['quote_midpoint'](selected)),
        'kickoff': milestone['start_date'], 'game_id': schedule['game_id'],
        'history': {'candles':len(points), 'valid_midpoints':sum(p['midpoint'] is not None for p in points),
                    'missing_interior_hours':missing_hours, 'points':points},
        'limitations': ['One event/selected-contract audit; no all-FBS market coverage or generic matching parser verified.',
                       'Quotes are saved snapshots, not live prices or executable fill guarantees.',
                       'Fresh schedule results do not update the older statistical snapshot.'],
    }
    (OUT/'market-audit.json').write_text(json.dumps(output,indent=2)+'\n')
    if not all(checks.values()): raise SystemExit('Market verification failed: '+str(checks))
    print(json.dumps({k:output[k] for k in ('sample_match_verified','contracts_returned','contracts_with_valid_midpoints','selected_contract')},indent=2))

if __name__ == '__main__': main()
