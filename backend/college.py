"""College research from validated saved data; no predictions or NFL metric substitution."""
from datetime import datetime, timezone
from fractions import Fraction
from statistics import median

from .sources.common import SourceError


def parse_time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('Missing timezone')
        return result
    except (ValueError, AttributeError) as error:
        raise SourceError('College schedule has an invalid kickoff timestamp.') from error


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

def index_rows(rows, team_key):
    index = {}
    for row in rows:
        key = (row['game_id'], row[team_key])
        if key in index: raise SourceError(f'Duplicate college statistics row {key}')
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
                                          if parsed and all(num(r.get('interceptions')) is not None for r in parsed) else None},
                'touchdowns':{'value':None,'reason':'Not supplied by the team-box source'}}
    if category.startswith('rushing'):
        return {'yards_per_game':ratio(boxes,'rushingYards'),
                'yards_per_carry':ratio(boxes,'rushingYards','rushingAttempts'),
                'touchdowns':{'value':None,'reason':'Not supplied by the team-box source'}}
    return {}

def build_variant(schedule, teams, tables, cutoff, include_fcs):
    games=[r for r in schedule if r['completed']=='true' and r['season_type'] in ('regular', 'postseason')
           and parse_time(r['start_date']) < parse_time(cutoff) and r['fbs_participant']=='true'
           and (include_fcs or r['fbs_game']=='true')]
    games.sort(key=lambda r:(parse_time(r['start_date']),r['game_id']))
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
    return {'include_fcs_performances':include_fcs,'scope':'Completed regular-season games; FBS teams only',
            'games_used':len(games),'teams':report}


def college_rankings(bundle, season, include_fcs=False, game_id=None, now=None):
    now = now or datetime.now(timezone.utc)
    schedule = bundle['schedule']
    teams = {g[side + '_id']: g[side + '_team'] for g in schedule for side in ('home', 'away')
             if g[side + '_division'] == 'fbs'}
    tables = {name: index_rows(bundle[name], key) for name, key in (
        ('team_box', 'team_id'), ('adv_team', 'pos_team_id'),
        ('adv_defensive', 'def_pos_team_id'), ('adv_situational', 'pos_team_id'))}
    result = build_variant(schedule, teams, tables, now.isoformat(), include_fcs)
    if game_id is not None:
        game = next((g for g in schedule if g['game_id'] == game_id and g['fbs_participant'] == 'true'), None)
        if game is None:
            raise SourceError('This college game is not in the saved FBS schedule.')
        result['teams'] = {key: value for key, value in result['teams'].items()
                           if key in (game['home_id'], game['away_id'])}
    result['season'] = season
    result['categories'] = [{'key': key, 'label': value[0], 'higher_is_better': value[1],
                              'opposing': value[2], 'measure': value[3]} for key, value in CATEGORIES.items()]
    completed = [g for g in schedule if g['completed'] == 'true' and g['fbs_participant'] == 'true'
                 and g['season_type'] in ('regular', 'postseason') and parse_time(g['start_date']) < now]
    with_statistics = [g for g in completed if all((g['game_id'], g[s + '_id']) in table
                       for table in tables.values() for s in ('home', 'away'))]
    result['latest_completed_kickoff'] = max((g['start_date'] for g in with_statistics), key=parse_time, default=None)
    result['missing_completed_games'] = len(completed) - len(with_statistics)
    result['team_count'] = len(teams)
    result['warnings'] = [
        'Published EPA is rounded to two decimals before averaging. Scrambles remain rushes; these measures differ from NFL EPA.',
        'Opponent context averages current opposing-unit metrics per meeting, including head-to-head games. It is not an adjusted rating.',
        'FBS membership follows the source classification. Full coverage has not been independently verified.',
    ]
    return normalize(result)


def reconcile_college_schedule(bundle, current):
    """Keep source statistics unchanged; update expected game coverage separately."""
    rows = {g['game_id']: dict(g, schedule_verified=False) for g in bundle['schedule']}
    warnings = []
    for game in current:
        old = rows.get(game['game_id'])
        changed = old and any(old[s + '_id'] != game[s + '_id'] for s in ('home', 'away'))
        resolved = changed and old['completed'] == 'false' and all(
            old[s + '_id'] == game[s + '_id'] or old[s + '_id'] in ('-1', '-2', '112350', '112351')
            for s in ('home', 'away'))
        if changed and not resolved and not game.get('neutral_labels_reversed'):
            warnings.append(f"Game {game['game_id']}: current participants conflict with the baseline; quotes withheld.")
            continue
        rows[game['game_id']] = game
    return {**bundle, 'schedule': list(rows.values())}, warnings


def college_matchups(bundle, season, week=None, now=None, season_type=None):
    now = now or datetime.now(timezone.utc)
    schedule = [g for g in bundle['schedule'] if g['season_type'] in ('regular', 'postseason')
                and (g['fbs_participant'] == 'true' or (g.get('fbs_scoreboard') and not g.get('participants_confirmed', True)))]
    def upcoming(game):
        if game['completed'] == 'true' or game.get('state') in ('in', 'post') or game.get('status') in ('STATUS_CANCELED', 'STATUS_CANCELLED'):
            return False
        if game.get('status') == 'STATUS_POSTPONED':
            return True
        kickoff = parse_time(game['start_date'])
        return kickoff.date() >= now.date() if game['start_time_tbd'] == 'true' else kickoff > now
    future = sorted((g for g in schedule if upcoming(g)), key=lambda g: parse_time(g['start_date']))
    selected_phase = season_type or (future[0]['season_type'] if future else 'regular')
    periods = sorted({(g['season_type'], int(g['week'])) for g in schedule}, key=lambda p: (p[0] != 'regular', p[1]))
    weeks = [w for phase, w in periods if phase == selected_phase]
    future = [g for g in future if g['season_type'] == selected_phase]
    selected_week = week if week is not None else int(future[0]['week']) if future else (weeks[-1] if weeks else 1)
    games = []
    for game in future:
        if int(game['week']) != selected_week:
            continue
        games.append({
            'game_id': game['game_id'], 'week': selected_week, 'season_type': selected_phase, 'kickoff': game['start_date'],
            'time_tbd': game['start_time_tbd'] == 'true', 'neutral': game['neutral_site'] == 'true',
            'venue': game.get('venue') or None,
            'schedule_verified': game.get('schedule_verified', False),
            'participants_confirmed': game.get('participants_confirmed', True),
            'status': game.get('status') or 'STATUS_SCHEDULED',
            **{side: {'id': game[side + '_id'], 'name': game[side + '_team'],
                      'is_fbs': game[side + '_division'] == 'fbs', 'division': game[side + '_division'],
                      'logo': f"https://a.espncdn.com/i/teamlogos/ncaa/500/{game[side + '_id']}.png"
                      if game[side + '_id'].isdigit() and game[side + '_division'] != 'unknown' else None}
               for side in ('home', 'away')},
        })
    overdue = sum(g['completed'] != 'true' and g['start_time_tbd'] != 'true'
                  and parse_time(g['start_date']) < now for g in schedule)
    return {'season': season, 'season_type': selected_phase, 'week': selected_week, 'weeks': weeks,
            'periods': [{'season_type': phase, 'week': w} for phase, w in periods], 'games': games,
            'overdue_games': overdue,
            'warnings': ['Saved schedule; refresh for kickoff changes and newly completed games.']}
