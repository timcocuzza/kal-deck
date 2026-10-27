"""Strength-only point forecasts. No prices, ATS updates or cover distributions.

Canonical sign is home final score minus away final score. Replay is reconstructed
from the current source revision; it is not an archive of forecasts issued live.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import groupby
import math

from .elo import APPROVED_CONFIG, CENTER, prepare_elo_history, replay_elo
from .matchups import TEAM_NAMES
from .college_rating import CONFIG
from .college_strength import calculate_strength

NFL_VERSION = 'nfl-elo-points-ols-v1'
CFB_VERSION = 'cfb-strength-benchmark-v1'
MIN_TRAINING = 256
TRAIN_START = 2007  # 2002–2006 warm up the unchanged NFL Elo model.
MAX_SOURCE_AGE_HOURS = 24


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


class PointsFit:
    """OLS through origin: margin = beta * (home Elo - away Elo + venue Elo).

    Zero intercept preserves neutral-site side symmetry. No fixed Elo/point
    conversion or probability transformation. Sufficient statistics are past-only.
    """
    def __init__(self):
        self.n = 0
        self.xx = self.xy = self.home_sum = 0.0
        self.home_n = 0
        self.cutoff = None

    @property
    def coefficient(self):
        value = self.xy / self.xx if self.xx else None
        return value if self.n >= MIN_TRAINING and value is not None and math.isfinite(value) and value > 0 else None

    def add(self, row):
        if row['season'] < TRAIN_START:
            return
        x = row['home_rating_before'] - row['away_rating_before'] + row['home_advantage']
        y = row['home_score'] - row['away_score']
        self.n += 1
        self.xx += x * x
        self.xy += x * y
        if not row['neutral']:
            self.home_sum += y
            self.home_n += 1
        self.cutoff = row['kickoff']

    def metadata(self):
        return {'points_per_elo': self.coefficient, 'training_games': self.n,
                'training_cutoff': self.cutoff, 'training_start_season': TRAIN_START,
                'formula': 'beta * (home Elo - away Elo + venue Elo); OLS through origin'}


def rolling_nfl(logs):
    """Freeze the fit for each UTC date, score all games, then learn results."""
    fit, predictions, waiting, last_played = PointsFit(), [], [], {}
    for day, batch in groupby(logs, key=lambda r: r['kickoff'][:10]):
        batch = list(batch)
        safe_before = stamp(day + 'T00:00:00+00:00') - timedelta(hours=24)
        ready = [r for r in waiting if stamp(r['kickoff']) < safe_before]
        waiting = [r for r in waiting if stamp(r['kickoff']) >= safe_before]
        for row in ready:
            fit.add(row)
        beta = fit.coefficient
        for row in batch:
            if any(last_played.get(row[side]) and stamp(last_played[row[side]]) >= safe_before for side in ('home_team', 'away_team')):
                raise ValueError('A participant has a prior result inside the historical availability embargo.')
            x = row['home_rating_before'] - row['away_rating_before'] + row['home_advantage']
            predictions.append({**row, 'home_margin': beta * x if beta is not None else None,
                                'prediction_as_of': day + 'T00:00:00+00:00', **fit.metadata(),
                                'home_only': 0 if row['neutral'] else fit.home_sum / fit.home_n if fit.home_n else None})
        for row in batch:
            for side in ('home_team', 'away_team'):
                last_played[row[side]] = row['kickoff']
        waiting.extend(batch)
    # Caller passes only embargo-eligible completed results for the live fit.
    for row in waiting:
        fit.add(row)
    return predictions, fit


def freshness(sources, now):
    output = []
    for source in sources:
        fetched = stamp(source.get('fetched_at'))
        age = (now - fetched).total_seconds() / 3600 if fetched else None
        state = ('unknown' if age is None or age < 0 else 'stale' if age > MAX_SOURCE_AGE_HOURS
                 else 'refresh_failed' if source.get('error') else 'fresh')
        output.append({'name': source.get('name'), 'fetched_at': source.get('fetched_at'),
                       'source_updated_at': source.get('source_updated_at'), 'age_hours': age,
                       'status': state, 'error': source.get('error')})
    return output


def envelope(game, season, sport, sources, now):
    return {'game_id': game['game_id'], 'season': season,
            'home_team_id': game['home'].get('id', game['home'].get('code')),
            'away_team_id': game['away'].get('id', game['away'].get('code')),
            'neutral': game['neutral'], 'kickoff': game['kickoff'],
            'model_version': NFL_VERSION if sport == 'nfl' else CFB_VERSION,
            'experimental': sport == 'cfb', 'home_margin': None,
            'prediction_as_of': now.isoformat(), 'ratings_as_of': (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=24)).isoformat(),
            'training_cutoff': None, 'source_freshness': freshness(sources, now),
            'available': False, 'unavailable_reason': None, 'notices': [],
            'result_embargo_hours': 24,
            'basis': 'strength_only', 'margin_convention': 'home_score_minus_away_score'}


def input_reason(forecast, now):
    start = stamp(forecast['kickoff'])
    if start is None:
        return 'Kickoff is unverified.'
    if start <= now:
        return 'Game has started; no archived pregame forecast is available here.'
    states = {s['status'] for s in forecast['source_freshness']}
    if not states or 'unknown' in states:
        return 'Source freshness is unknown. Refresh schedule and strength history.'
    if 'stale' in states:
        return 'Saved inputs are older than 24 hours. Refresh schedule and strength history.'
    if 'refresh_failed' in states:
        forecast['notices'].append('Source refresh failed; using the saved snapshot less than 24 hours old.')
    return None


def attach_nfl_margins(report, rows, sources, *, now=None):
    now = now or datetime.now(timezone.utc)
    freeze = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=24)
    error, schedule, ratings, fit, counts = None, [], {}, PointsFit(), Counter()
    if rows is None:
        error = 'NFL Elo history has not been downloaded.'
    else:
        try:
            schedule = prepare_elo_history(rows, end_season=report['season'], as_of=now)
            completed = [g for g in schedule if g['home_score'] is not None and stamp(g['kickoff']) < freeze]
            replay = replay_elo(completed, APPROVED_CONFIG, teams=TEAM_NAMES, freeze_dates=True)
            _, fit = rolling_nfl(replay['games'])
            ratings = replay['ratings']
            if report['season'] not in replay['season_openings']:
                ratings = {t: CENTER + (r - CENTER) * APPROVED_CONFIG.offseason_retention for t, r in ratings.items()}
            counts.update(t for g in completed if g['season'] == report['season'] for t in (g['home_team'], g['away_team']))
        except (ValueError, KeyError, TypeError):
            error = 'NFL history failed validation; refresh and review the source.'
    by_id = {g['game_id']: g for g in schedule}
    pending = {t for g in schedule if g['home_score'] is None and stamp(g['kickoff']) < freeze for t in (g['home_team'], g['away_team'])}
    for game in report['games']:
        f = envelope(game, report['season'], 'nfl', sources, now)
        game['margin_forecast'] = f
        f.update(calibration=fit.metadata(), training_cutoff=fit.cutoff)
        reason = error or input_reason(f, now)
        g = by_id.get(game['game_id'])
        home, away = f['home_team_id'], f['away_team_id']
        if not reason and (not g or not game.get('venue_verified') or
                           (g['home_team'], g['away_team'], g['season'], g['neutral'], stamp(g['kickoff']), str(g['week'])) !=
                           (home, away, report['season'], game['neutral'], stamp(game['kickoff']), str(game['week']))):
            reason = 'Schedule and Elo matchup context disagree or venue is unverified.'
        if not reason and g['home_score'] is not None:
            reason = 'Game is completed in strength history.'
        if not reason and pending.intersection((home, away)):
            reason = 'A participant has an earlier game awaiting a published score.'
        if not reason and fit.coefficient is None:
            reason = 'Insufficient historical games or invalid Elo-to-points fit.'
        if not reason:
            advantage = 0 if game['neutral'] else APPROVED_CONFIG.home_advantage
            f['home_margin'] = fit.coefficient * (ratings[home] - ratings[away] + advantage)
            if min(counts[home], counts[away]) < 3:
                f['notices'].append('Early season: fewer than three games for a participant; offseason ratings have more influence.')
        f.update(available=reason is None, unavailable_reason=reason)


def attach_college_margins(report, bundle, sources, *, now=None):
    now = now or datetime.now(timezone.utc)
    freeze = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=24)
    strength, error = None, None
    try:
        if bundle is None:
            error = 'College strength history has not been downloaded.'
        else:
            strength = calculate_strength(bundle, report['season'], now=freeze)
    except (ValueError, KeyError, TypeError):
        error = 'College strength history failed validation; refresh and review the source.'
    teams = {t['id']: t for t in strength['teams']} if strength else {}
    by_id = {g['id']: g for g in bundle['games']} if bundle else {}
    cutoff = max((g['kickoff'] for g in by_id.values() if g['completed'] and g['season'] <= report['season'] and stamp(g['kickoff']) < freeze), default=None)
    for game in report['games']:
        f = envelope(game, report['season'], 'cfb', sources, now)
        game['margin_forecast'] = f
        f.update(training_cutoff=cutoff, calibration={'formula': 'home strength - away strength + venue advantage',
                                                      'home_advantage_points': CONFIG['home']})
        reason = error or input_reason(f, now)
        home, away = f['home_team_id'], f['away_team_id']
        g = by_id.get(game['game_id'])
        if not reason and (not game.get('schedule_verified') or not game.get('participants_confirmed') or game.get('time_tbd')
                           or game.get('status') != 'STATUS_SCHEDULED'):
            reason = 'Matchup, participants or kickoff are not verified.'
        if not reason and (not g or type(g.get('neutral')) is not bool or
                           (g['season'], g['home'], g['away'], g['neutral'], stamp(g['kickoff']), g['phase'], g['week']) !=
                           (report['season'], home, away, game['neutral'], stamp(game['kickoff']), game['season_type'], game['week'])):
            reason = 'Schedule and strength matchup, venue or season context disagree.'
        if not reason and (g['completed'] or g['canceled'] or g['status'] != 'STATUS_SCHEDULED'):
            reason = 'Strength history does not confirm an upcoming game.'
        if not reason and (not game['home']['is_fbs'] or not game['away']['is_fbs']):
            reason = 'FCS strength is internal only; no public matchup estimate.'
        if not reason and (home not in teams or away not in teams):
            reason = 'A participant has no verified FBS strength for this season.'
        if not reason and (teams[home]['awaiting_final_ids'] or teams[away]['awaiting_final_ids']):
            reason = 'A participant has an earlier game awaiting a confirmed final.'
        if not reason:
            f['home_margin'] = teams[home]['rating'] - teams[away]['rating'] + (0 if game['neutral'] else CONFIG['home'])
            f['notices'] = list(dict.fromkeys(f['notices'] + teams[home]['notices'] + teams[away]['notices']))
            f['notices'].append('Experimental benchmark; margin calibration has not been independently validated.')
        f.update(available=reason is None, unavailable_reason=reason)
