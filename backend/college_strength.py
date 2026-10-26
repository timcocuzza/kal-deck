"""FBS-only presentation of overall strength, schedule context and result evidence."""
from collections import defaultdict
from dataclasses import fields
from datetime import datetime, timezone
from statistics import mean

from .college_rating import CONFIG, Game, replay
from .sources.common import SourceError


def ranks(values):
    ordered = sorted(values.values(), reverse=True)
    first = {}
    for index, value in enumerate(ordered, 1):
        first.setdefault(value, index)
    return {key: first[value] for key, value in values.items()}


def calculate_strength(bundle, season, *, now=None):
    now = now or datetime.now(timezone.utc)
    roster = bundle['rosters'].get(str(season))
    if not roster:
        raise SourceError('College rating season membership is unavailable.')
    keys = {f.name for f in fields(Game)}
    completed = [g for g in bundle['games'] if g['completed'] and g['season'] <= season
                 and datetime.fromisoformat(g['kickoff']) < now]
    games = [Game(**{k: g[k] for k in keys}) for g in sorted(completed, key=lambda g: (g['day'], g['id']))]
    logs = replay(games, CONFIG)
    values, last_div, last_season, active_prior = {}, {}, {}, set()
    for row in logs:
        g = row['game']
        if g.season >= season:
            break
        for side in ('home', 'away'):
            tid = getattr(g, side)
            values[tid] = row[side + '_after']
            last_div[tid], last_season[tid] = getattr(g, side + '_div'), g.season
            if g.season == season - 1:
                active_prior.add(tid)
    centers = {div: mean([values[t] for t in sorted(active_prior) if last_div[t] == div])
               if any(last_div[t] == div for t in active_prior) else 0.0 for div in ('fbs', 'fcs')}
    openings, historical_counts = {}, defaultdict(int)
    for g in games:
        if g.season < season:
            historical_counts[g.home] += 1
            historical_counts[g.away] += 1
    for tid, team in roster.items():
        if tid in values:
            center = centers[last_div[tid]]
            openings[tid] = center + CONFIG['retention'] ** (season - last_season[tid]) * (values[tid] - center)
        else:
            openings[tid] = centers[team['division']]
    # First appearances agree exactly with the production replay, including
    # missing-season histories and division changes.
    current_logs = [r for r in logs if r['game'].season == season]
    for tid in roster:
        first = next((r for r in current_logs if tid in (r['game'].home, r['game'].away)), None)
        if first:
            side = 'home' if first['game'].home == tid else 'away'
            openings[tid] = first[side + '_before']
    latest = openings.copy()
    for row in current_logs:
        latest[row['game'].home], latest[row['game'].away] = row['home_after'], row['away_after']
    fbs = {t: data for t, data in roster.items() if data['division'] == 'fbs'}
    current_ranks = ranks({t: latest[t] for t in fbs})
    before_ranks, day_values = {}, openings.copy()
    by_day = defaultdict(list)
    for row in current_logs:
        by_day[row['game'].day].append(row)
    for day in sorted(by_day):
        rank = ranks({t: day_values[t] for t in fbs})
        for row in by_day[day]:
            before_ranks[row['game'].id] = rank
        for row in by_day[day]:
            day_values[row['game'].home], day_values[row['game'].away] = row['home_after'], row['away_after']
    pending = [g for g in bundle['games'] if g['season'] == season and not g['completed'] and not g['canceled']
               and g['status'] != 'STATUS_POSTPONED' and datetime.fromisoformat(g['kickoff']) < now]
    result = []
    for tid, team in fbs.items():
        own_logs, faced, opponents_now = [], [], []
        for row in current_logs:
            g = row['game']
            if tid not in (g.home, g.away):
                continue
            side, other = ('home', 'away') if tid == g.home else ('away', 'home')
            opponent = getattr(g, other)
            is_fbs = getattr(g, other + '_div') == 'fbs'
            own_score, other_score = getattr(g, side + '_score'), getattr(g, other + '_score')
            outcome = 'W' if own_score > other_score else 'L' if own_score < other_score else 'T'
            venue = 'neutral' if g.neutral else side
            difficulty_adjustment = 0 if g.neutral else -CONFIG['home'] if side == 'home' else CONFIG['home']
            faced.append(row[other + '_before'] + difficulty_adjustment)
            opponents_now.append(latest[opponent] + difficulty_adjustment)
            own_logs.append({'game_id': g.id, 'date': g.kickoff, 'week': g.week, 'opponent_id': opponent,
                             'opponent': getattr(g, other + '_name'), 'opponent_is_fbs': is_fbs, 'venue': venue,
                             'result': outcome, 'team_score': own_score, 'opponent_score': other_score,
                             'rating_before': row[side + '_before'], 'rating_after': row[side + '_after'],
                             'change': row['home_change'] * (1 if side == 'home' else -1),
                             'opponent_pregame_rating': row[other + '_before'] if is_fbs else None,
                             'opponent_pregame_rank': before_ranks[g.id].get(opponent) if is_fbs else None,
                             'opponent_current_rating': latest[opponent] if is_fbs else None,
                             'opponent_current_rank': current_ranks.get(opponent) if is_fbs else None,
                             'benchmark': row['benchmark'] * (1 if side == 'home' else -1) if is_fbs else None})
        wins = [g for g in own_logs if g['result'] == 'W']
        losses = [g for g in own_logs if g['result'] == 'L']
        top25 = [g for g in own_logs if g['opponent_current_rank'] is not None and g['opponent_current_rank'] <= 25]
        def evidence(items, reverse=False):
            eligible = [g for g in items if g['opponent_current_rank'] is not None]
            return sorted(eligible, key=lambda g: (g['opponent_current_rank'], g['game_id']), reverse=reverse)[:3]
        awaiting = [g['id'] for g in pending if tid in (g['home'], g['away'])]
        notices = []
        if len(own_logs) < 3:
            notices.append('Early season: fewer than three rated games.')
        if historical_counts[tid] < 12:
            notices.append('Limited prior Division I history; division prior has more influence.')
        if awaiting:
            notices.append(f'{len(awaiting)} started games await confirmed final results.')
        result.append({'id': tid, 'name': team['name'], 'rating': latest[tid], 'rank': current_ranks[tid],
                       'season_start_rating': openings[tid], 'season_change': latest[tid] - openings[tid],
                       'last_change': own_logs[-1]['change'] if own_logs else None,
                       'record': {'wins': len(wins), 'losses': len(losses), 'ties': len(own_logs) - len(wins) - len(losses)},
                       'fbs_record': {key: sum(g['result'] == code and g['opponent_is_fbs'] for g in own_logs)
                                      for key, code in [('wins', 'W'), ('losses', 'L'), ('ties', 'T')]},
                       'vs_current_top25': {'wins': sum(g['result'] == 'W' for g in top25), 'losses': sum(g['result'] == 'L' for g in top25)},
                       'schedule_faced': mean(faced) if faced else None,
                       'opponents_now': mean(opponents_now) if opponents_now else None,
                       'games_rated': len(own_logs), 'awaiting_final_ids': awaiting,
                       'strongest_wins': evidence(wins), 'losses_to_lower_rated_teams': evidence(losses, True),
                       'games': own_logs, 'notices': notices})
    for field in ('schedule_faced', 'opponents_now'):
        rank = ranks({t['id']: t[field] for t in result if t[field] is not None})
        for team in result:
            team[field + '_rank'] = rank.get(team['id'])
    return {'season': season, 'available': True, 'config': CONFIG, 'units': 'points of strength',
            'teams': sorted(result, key=lambda t: (t['rank'], t['name'])),
            'latest_result': max((g.kickoff for g in games if g.season == season), default=None),
            'replayed_games': len(games), 'awaiting_final_count': len(pending),
            'methodology': ['Strength order is not an AP poll or an automatic top-25 ballot. Results and schedule context support your own order.',
                            'Top-25 opponent records use current Deck strength ranks, not AP ranks. Opponents now includes all their rated results, including this meeting.',
                            'Schedule difficulty averages opponent strength per completed game, minus two at home, plus two away, zero at neutral sites. Higher is harder. FCS opponents count internally.',
                            'Pregame ranks use ratings before that UTC date. A win may lower strength; the win remains in the record.',
                            'Benchmarks explain rating changes; they are not calibrated market spreads or cover probabilities.'],
            'warnings': ['Development rating: source completeness and season membership remain subject to review.']}
