"""Local UI acceptance fixture; synthetic games/quotes, real forecast functions.

Run after npm run build: PYTHONPATH=.:tests .venv/bin/python tests/preview_margins.py
No production storage, personal records, source refresh or external requests.
"""
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from test_margins import cfb_fixture, nfl_fixture, NOW, SOURCES
from backend.margins import attach_nfl_margins, attach_college_margins
from backend.college_strength import calculate_strength
from backend.elo import calculate_elo
from backend.matchups import TEAM_NAMES


def market(ticker, tid, name, threshold):
    return dict(ticker=ticker, event_ticker='UI-FIXTURE', team_id=tid, team=name,
                threshold=threshold, operator='gt', no_push=True, spread=-threshold,
                label=f'{name} −{threshold}', wording=f'{name} wins by over {threshold} points',
                rules='UI fixture: Yes settles only when the named team wins by strictly more than the half-point threshold. No push.',
                rules_secondary='', midpoint=.5, yes_bid_dollars='.48', yes_ask_dollars='.52',
                no_bid_dollars='.48', no_ask_dollars='.52')


nfl, rows = nfl_fixture()
nfl['games'][0]['game_id'] = rows[-1]['game_id'] = '2026_02_LA_ARI'
attach_nfl_margins(nfl, rows, SOURCES, now=NOW)
ng = nfl['games'][0]
for side in ('home', 'away'):
    code = ng[side]['code']
    ng[side].update(name=TEAM_NAMES[code], logo=None,
                    research=dict(coverage=None, coverage_note='UI fixture', injuries=[], injury_note='UI fixture',
                                  injuries_available=False, depth=[], depth_date=None))
ng.update(date='2026-11-01', stadium='UI acceptance fixture', markets=[market('KXNFLSPREAD-FIXTURE-H7', ng['home']['code'], ng['home']['code'], 7.5),
             market('KXNFLSPREAD-FIXTURE-A3', ng['away']['code'], ng['away']['code'], 3.5)], default_market_ticker='KXNFLSPREAD-FIXTURE-H7', spread_status='available')
nfl.update(week=2, weeks=[2], warnings=['UI acceptance fixture — synthetic results and quotes.'], sources=[], issues=[])
elo = calculate_elo(2026, rows, now=NOW); elo.update(available=True, sources=[])
cfb, history = cfb_fixture()
# Use real display IDs for colors/abbreviations; all game/results remain synthetic.
ids = {'1': '194', '2': '130'}
names = {'194': 'Ohio State', '130': 'Michigan'}
for g in history['games']:
    for side in ('home', 'away'):
        g[side] = ids[g[side]]
        g[side + '_name'] = names[g[side]]
history['rosters']['2026'] = {ids[t]: {**v, 'id': ids[t], 'name': names[ids[t]]} for t, v in history['rosters']['2026'].items()}
for side in ('home', 'away'):
    cfb['games'][0][side]['id'] = ids[cfb['games'][0][side]['id']]
attach_college_margins(cfb, history, SOURCES, now=NOW)
cg = cfb['games'][0]
cg['home'].update(name='Ohio State', division='fbs', logo=None)
cg['away'].update(name='Michigan', division='fbs', logo=None)
cg.update(venue='UI acceptance fixture', markets=[market('KXNCAAFSPREAD-FIXTURE-H7', '194', 'Ohio State', 7.5), market('KXNCAAFSPREAD-FIXTURE-H14', '194', 'Ohio State', 14.5),
           market('KXNCAAFSPREAD-FIXTURE-A3', '130', 'Michigan', 3.5)], default_market_ticker='KXNCAAFSPREAD-FIXTURE-H7', spread_status='available')
cfb.update(available=True, week=1, weeks=[1], season_type='regular', periods=[{'season_type':'regular','week':1}],
           warnings=['UI acceptance fixture — synthetic results and quotes.'], sources=[], issues=[])
strength = calculate_strength(history, 2026, now=NOW); strength['sources'] = []
# A second fixture explicitly exercises stale inputs without hiding the game.
stale = deepcopy(cg); stale['game_id'] = '3'; stale['margin_forecast'].update(game_id='3', available=False, home_margin=None,
    unavailable_reason='Saved inputs are older than 24 hours. Refresh schedule and strength history.')
stale['margin_forecast']['notices'] = []; stale['markets'] = []; stale['default_market_ticker'] = None
stale['spread_status'] = 'Spread unavailable'; cfb['games'].append(stale)


class Preview(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/'):
            data = {'sources': []}
            if path == '/api/matchups': data = nfl
            elif path == '/api/elo': data = elo
            elif path == '/api/cfb/matchups': data = cfb
            elif path == '/api/cfb/strength': data = strength
            elif path == '/api/watchlist': data = {'entries': []}
            elif path in ('/api/rankings', '/api/position-defense'): data = {'teams': [], 'categories': [], 'sources': [], 'warnings': []}
            elif path == '/api/cfb/rankings': data = {'available': False, 'sources': [], 'warnings': ['UI fixture has no facet statistics.']}
            elif path.endswith('/history'):
                query = parse_qs(urlsplit(self.path).query)
                data = {'points': [], 'candles': [], 'fetched_at': NOW.isoformat(), 'url': '',
                        'context': {'ticker': path.split('/')[-2], 'series': path.split('/')[-3], 'start_ts': int(query['start'][0]), 'end_ts': int(query['end'][0]), 'interval_minutes': 60}}
            body = json.dumps(data).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)
        else:
            super().do_GET()


if __name__ == '__main__':
    print('UI fixture: http://127.0.0.1:8765 — synthetic data, no personal records', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), partial(Preview, directory=str(Path('dist').resolve()))).serve_forever()
