"""Reproducible, read-only CFB feasibility audit over cached public season CSVs.

Run fetch_sources.py first, then this script. This is not product code. Published
rounded per-game EPA provides a labeled candidate metric, not exact NFL parity.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
from statistics import median

from fetch_sources import CACHE, read_csv

OUT = Path(__file__).resolve().parent
CATEGORIES = {
    'passing_offense': ('Passing offense', True, 'passing_defense', 'Published pass EPA / play'),
    'passing_defense': ('Passing defense', False, 'passing_offense', 'Published pass EPA allowed / play'),
    'rushing_offense': ('Rushing offense', True, 'rushing_defense', 'Published rush EPA / play'),
    'rushing_defense': ('Rushing defense', False, 'rushing_offense', 'Published rush EPA allowed / play'),
    'pass_rush': ('Pass rush', True, 'pass_protection', 'Sacks / game'),
    'pass_protection': ('Pass protection', False, 'pass_rush', 'Sacks allowed / game'),
}

def num(value):
    try:
        return Fraction(value) if value not in (None, '', 'NA', 'NaN', 'nan') else None
    except (ValueError, ZeroDivisionError):
        return None

def mean(values):
    values = [v for v in values if v is not None]
    return sum(values, Fraction()) / len(values) if values else None

def normalize(value):
    if isinstance(value, Fraction): return float(value)
    if isinstance(value, dict): return {k:normalize(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [normalize(v) for v in value]
    return value

def write(name, value):
    (OUT/name).write_text(json.dumps(normalize(value), indent=2, ensure_ascii=False, allow_nan=False)+'\n')

def index_rows(rows, team_key):
    index = {}
    for row in rows:
        key = (row['game_id'], row[team_key])
        if key in index: raise ValueError(f'Duplicate data row {key}')
        index[key] = row
    return index

def ratio(rows, numerator, denominator=None, split=False):
    pairs=[]
    for row in rows:
        if split:
            parts=row.get('completionAttempts','').split('/')
            n,d=(num(v) for v in parts) if len(parts)==2 else (None,None)
        else:
            n=num(row.get(numerator)); d=num(row.get(denominator)) if denominator else Fraction(1)
        if n is not None and d is not None: pairs.append((n,d))
    total_d=sum((d for _,d in pairs),Fraction())
    return {'value':sum((n for n,_ in pairs),Fraction())/total_d if total_d else None,
            'games_used':len(pairs),'games_expected':len(rows)}

def supporting(boxes, category):
    if category.startswith('passing'):
        # Official box completionAttempts are parsed; no inference from rounded YPA.
        parsed=[]
        for row in boxes:
            row=dict(row); parts=row.get('completionAttempts','').split('/')
            if len(parts)==2: row['attempts']=parts[1]
            parsed.append(row)
        return {'yards_per_game':dict(ratio(parsed,'netPassingYards'),label='Net passing yards / game'),
                'yards_per_attempt':dict(ratio(parsed,'netPassingYards','attempts'),label='Net passing yards / attempt'),
                'completion_fraction':ratio(parsed,None,split=True),
                'interceptions':{'value':sum((num(r.get('interceptions')) for r in parsed),Fraction())
                                          if all(num(r.get('interceptions')) is not None for r in parsed) else None},
                'touchdowns':{'value':None,'reason':'Not supplied by audited team-box dataset'}}
    if category.startswith('rushing'):
        return {'yards_per_game':ratio(boxes,'rushingYards'),
                'yards_per_carry':ratio(boxes,'rushingYards','rushingAttempts'),
                'touchdowns':{'value':None,'reason':'Not supplied by audited team-box dataset'}}
    return {}

def build_variant(schedule, teams, tables, cutoff, include_fcs):
    games=[r for r in schedule if r['completed']=='true' and r['season_type']=='regular'
           and r['start_date'] < cutoff and r['fbs_participant']=='true'
           and (include_fcs or r['fbs_game']=='true')]
    games.sort(key=lambda r:(r['start_date'],r['game_id']))
    report={}
    for team_id, name in sorted(teams.items(), key=lambda p:p[1]):
        own_games=[g for g in games if team_id in (g['home_id'],g['away_id'])]
        cats={}
        for category,(label,descending,opposing,unit) in CATEGORIES.items():
            logs=[]; boxes=[]; success=[]
            for game in own_games:
                gid=game['game_id']; side='home' if game['home_id']==team_id else 'away'
                other='away' if side=='home' else 'home'; opponent=game[other+'_id']
                key=(gid,team_id); oppkey=(gid,opponent)
                if category=='pass_rush': value=num(tables['adv_defensive'].get(key,{}).get('sacks'))
                elif category=='pass_protection': value=num(tables['adv_defensive'].get(oppkey,{}).get('sacks'))
                else:
                    statkey=oppkey if category.endswith('defense') else key
                    prefix='passing' if category.startswith('passing') else 'rushing'
                    value=num(tables['adv_team'].get(statkey,{}).get(f'EPA_{prefix}_per_play'))
                    boxes.append(tables['team_box'].get(statkey,{}))
                    if prefix=='rushing': success.append(num(tables['adv_situational'].get(statkey,{}).get('EPA_success_rush_rate')))
                logs.append({'game_id':gid,'date':game['start_date'],'opponent_id':opponent,
                             'opponent':game[other+'_team'],'opponent_is_fbs':opponent in teams,
                             'venue_side':side,'value':value,'opponent_current_rank':None,
                             'opponent_current_metric':None})
            vals=[r['value'] for r in logs]; valid=[v for v in vals if v is not None]
            support=supporting(boxes,category)
            if success: support['positive_epa_success_fraction']={'value':mean(success),'games_used':sum(v is not None for v in success),'games_expected':len(own_games)}
            cats[category]={'label':label,'unit':unit,'value':mean(vals),'rank':None,
                            'games_used':len(valid),'games_expected':len(own_games),
                            'missing_game_ids':[r['game_id'] for r in logs if r['value'] is None],
                            'supporting':support,'games':logs,
                            'exact_nfl_metric_parity':'blocked' if category not in ('pass_rush','pass_protection') else 'same headline definition; upstream count validation still limited',
                            'candidate_metric_status':'source-rounded game means' if category not in ('pass_rush','pass_protection') else 'integer counts averaged exactly'}
        report[team_id]={'team_id':team_id,'name':name,'categories':cats,'games_expected':len(own_games)}
    for category,(_,descending,opposing,_) in CATEGORIES.items():
        ordered=sorted((t for t in report.values() if t['categories'][category]['value'] is not None),
                       key=lambda t:t['categories'][category]['value'],reverse=descending)
        previous=None; rank=None
        for position,t in enumerate(ordered,1):
            metric=t['categories'][category]
            if metric['value']!=previous: rank=position;previous=metric['value']
            metric['rank']=rank
    # All six rank sets must exist before opponent-context joins.
    for category,(_,descending,opposing,_) in CATEGORIES.items():
        ordered=[t for t in report.values() if t['categories'][category]['value'] is not None]
        values=[t['categories'][category]['value'] for t in ordered]
        summary={'mean':mean(values),'median':median(values) if values else None,'teams_ranked':len(values),'teams_expected':len(teams)}
        for team in report.values():
            metric=team['categories'][category]; metric['league']=summary
            opponent_values=[]
            for row in metric['games']:
                # Never publish FCS team metrics, even in inclusion sensitivity mode.
                other=report.get(row['opponent_id'])
                if other:
                    om=other['categories'][opposing]
                    row['opponent_current_rank']=om['rank']; row['opponent_current_metric']=om['value']
                    opponent_values.append(om['value'])
            metric['schedule_context']={'opponent_category':opposing,'average_opponent_metric':mean(opponent_values),
                'opponents_used':sum(v is not None for v in opponent_values),'games_expected':len(metric['games']),
                'method':'Equal weight per meeting; current season opposing-unit averages include head-to-head games. FCS opponent metrics omitted. Not a recursive or adjusted SoS rating.'}
    return {'include_fcs_performances':include_fcs,'scope':'2026 completed regular-season games before cutoff, all FBS teams ranked',
            'games_used':len(games),'teams':report}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cutoff',default='2026-10-24T00:00:00.000Z');args=parser.parse_args()
    manifest=json.loads((CACHE/'manifest.json').read_text())
    data={k:read_csv(v['path']) for k,v in manifest.items()};schedule=data['schedule']
    ids=[g['game_id'] for g in schedule]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate scheduled game ID')
    teams={g[side+'_id']:g[side+'_team'] for g in schedule for side in ('home','away') if g[side+'_division']=='fbs'}
    tables={k:index_rows(data[k],teamkey) for k,teamkey in [('team_box','team_id'),('adv_team','pos_team_id'),('adv_defensive','def_pos_team_id'),('adv_situational','pos_team_id')]}
    completed={g['game_id']:g for g in schedule if g['completed']=='true' and g['fbs_participant']=='true' and g['start_date']<args.cutoff}
    expected={(gid,g[side+'_id']) for gid,g in completed.items() for side in ('home','away')}
    coverage={k:{'rows':len(table),'missing_game_team_rows':[list(x) for x in sorted(expected-set(table))],
                 'extra_game_team_rows':[list(x) for x in sorted(set(table)-expected)]} for k,table in tables.items()}
    checks={'duplicate_keys':'none','counts_vs_schedule':coverage,'epa_rounding':{}}
    for family in ('passing','rushing'):
        countkey='passes' if family=='passing' else 'rushes'
        discrepancies=[]
        for key,r in tables['adv_team'].items():
            n,d,v=(num(r.get(k)) for k in (f'EPA_{family}_overall',countkey,f'EPA_{family}_per_play'))
            if n is not None and d and v is not None and abs(n/d-v)>Fraction('0.0055'): discrepancies.append(list(key))
        checks['epa_rounding'][family]={'rows_outside_rounded_tolerance':discrepancies,
            'check':'Published total/count vs published per-play value; tolerance .0055 allows two-decimal upstream rounding. Does not validate raw plays.'}
    matchup=next(g for g in schedule if {g['home_id'],g['away_id']}=={'2116','252'})
    variants={name:build_variant(schedule,teams,tables,args.cutoff,include) for name,include in [('fbs_only',False),('including_fcs_performances',True)]}
    methods={'cutoff':args.cutoff,'cutoff_note':'Conservative start-of-day cutoff; sample schedule kickoff is TBD. Market linkage must be independently verified.',
      'epa':'Equal-weight mean of source-published per-game EPA/play values, already rounded to two decimals. These are candidate research ranks, not the approved NFL exact metric.',
      'nfl_parity_blockers':['No scramble flag: scrambles remain runs; NFL defines them as dropbacks.','Published game EPA is rounded; exact unrounded play aggregation not audited.','Upstream play inclusion/penalty and garbage-time handling not independently reproduced in this CSV audit.'],
      'support':'Source team-box NET passing yardage and completion/attempt values; season ratios divide totals. Net passing yards/attempt is not asserted equivalent to the NFL passing-yard metric. Rushing positive-EPA success averages per-game fractions equally. Passing/rushing TD totals unavailable in audited tables. See independent-review.json for one upstream net-yardage/attempt discrepancy.',
      'ranking':'FBS teams only, higher/lower as existing NFL categories; competition ties using exact rational representations of published values. No minimum sample threshold.',
      'fcs':'Two sensitivity variants; no standalone FCS rankings or opponent season metrics. The inclusion variant includes FBS offensive and defensive performance against FCS opponents. This does not approve either product behavior.',
      'schedule_context':'Mean current opposing-unit metric per meeting, with FCS opponents omitted; includes head-to-head performances, matching existing NFL sack-context convention.'}
    dates=[g['start_date'] for g in completed.values()]
    past_uncompleted=[{'game_id':g['game_id'],'date':g['start_date'],'home':g['home_team'],'away':g['away_team']} for g in schedule
                       if g['fbs_participant']=='true' and g['completed']!='true' and g['start_date']<args.cutoff and g['start_time_tbd']!='true']
    audit={'generated_at':datetime.now(timezone.utc).isoformat(),'sources':manifest,'methodology':methods,
           'schedule':{'fbs_teams':len(teams),'completed_fbs_participant_games':len(completed),'latest_completed_kickoff':max(dates),
                       'past_games_not_marked_completed':past_uncompleted,'sample_matchup':matchup},'checks':checks,
           'variants':{k:{'games_used':v['games_used'],'ranked_teams':len(v['teams'])} for k,v in variants.items()}}
    write('stats-audit.json',audit)
    write('rankings.json',{'methodology':methods,'variants':variants})
    sample={'matchup':matchup,'sources':manifest,'methodology':methods,'results_through':max(dates),'variants':{}}
    for k,v in variants.items(): sample['variants'][k]={'games_used':v['games_used'],'teams':{tid:v['teams'][tid] for tid in ('252','2116')}}
    write('sample-matchup.json',sample)
    print(json.dumps(normalize({'audit':audit['schedule'],'checks':checks,'sample':{k:{t:v['teams'][t]['categories'] for t in ('252','2116')} for k,v in variants.items()}}))[:1000])
    print('Wrote stats-audit.json, rankings.json, sample-matchup.json')

if __name__=='__main__': main()
