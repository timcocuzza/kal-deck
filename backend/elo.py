"""Auditable NFL Elo replay and the user-approved production model.

Margin adjustment reference:
https://github.com/fivethirtyeight/nfl-elo-game/blob/master/forecast.py
Our approved initialization/league center is 1500, starting with the 2002 season.
The probability-shaped output is expected score: P(win) + 0.5 * P(tie).
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from statistics import median
from itertools import groupby

from .matchups import TEAM_NAMES, canonical, kickoff
from .rankings import number
from .sources.common import SourceError


CENTER = 1500.0
SCALE = 400.0
PHASES = {'REG', 'WC', 'DIV', 'CON', 'SB'}
RELOCATIONS = {'OAK': 'LV', 'STL': 'LA', 'SD': 'LAC'}


def franchise(code):
    return RELOCATIONS.get(code, canonical(code))


@dataclass(frozen=True)
class EloConfig:
    k: float
    home_advantage: float
    offseason_retention: float

    def __post_init__(self):
        if (any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                for value in (self.k, self.home_advantage, self.offseason_retention))
                or self.k <= 0 or not 0 <= self.offseason_retention <= 1):
            raise ValueError('Elo settings must be finite, with positive K and retention between zero and one.')


def expected_score(rating_difference):
    """Stable logistic conversion on the conventional 400-point Elo scale."""
    exponent = abs(rating_difference) * math.log(10) / SCALE
    tail = math.exp(-exponent)
    return 1 / (1 + tail) if rating_difference >= 0 else tail / (1 + tail)


def margin_multiplier(home_score, away_score, adjusted_home_difference):
    margin = abs(home_score - away_score)
    if margin == 0:
        return math.log(2) * 2.2
    winner_difference = adjusted_home_difference if home_score > away_score else -adjusted_home_difference
    denominator = 2.2 + winner_difference * 0.001
    if denominator <= 0:
        raise SourceError('Elo margin correction is outside its valid range; settings require review.')
    return math.log(margin + 1) * 2.2 / denominator


APPROVED_CONFIG = EloConfig(20, 50, 2 / 3)
SCORE_NOTICE = ('Completion follows published nflverse scores after kickoff; the source has no explicit final-status field. '
                'Games without both scores do not update Elo.')


def prepare_elo_history(rows, start_season=2002, end_season=2025, *, as_of=None):
    """Validate completed historical games before any parameter experiments.

    With as_of, permit unscored games in the final season and validate the production
    franchise set. Earlier seasons must be scored. Missing seasons/franchises and
    invalid rows fail closed; this cannot independently detect every omitted game.
    """
    if start_season < 2002 or end_season < start_season:
        raise SourceError('Invalid historical Elo season window.')
    result, seen, team_dates = [], set(), set()
    season_teams = {}
    for row in rows:
        season = number(row.get('season'))
        if season is None or season.denominator != 1 or not start_season <= season <= end_season:
            continue
        if row.get('game_type') not in PHASES:
            if row.get('game_type') == 'PRE':
                continue
            raise SourceError('Unrecognized game phase in Elo history.')
        season = int(season)
        gid = row.get('game_id')
        home, away = franchise(row.get('home_team')), franchise(row.get('away_team'))
        start = kickoff(row)
        if (not gid or gid in seen or not home or not away or home == away or start is None
                or row.get('location') not in ('Home', 'Neutral')):
            raise SourceError('Elo history contains duplicate, missing or invalid game identity, kickoff or venue data.')
        scores = [number(row.get(key)) for key in ('home_score', 'away_score')]
        unscored = all(row.get(key) in (None, '') for key in ('home_score', 'away_score'))
        pending = as_of is not None and season == end_season and unscored
        if not pending and any(score is None or score < 0 or score.denominator != 1 for score in scores):
            raise SourceError('Historical Elo replay requires complete, nonnegative integer final scores.')
        if as_of is not None and not pending and start >= as_of:
            raise SourceError('Elo source supplied scores before kickoff; the snapshot requires review.')
        for team in (home, away):
            key = team, row['gameday']
            if key in team_dates:
                raise SourceError('A team appears twice on one date; historical Elo ordering requires review.')
            team_dates.add(key)
        seen.add(gid)
        season_teams.setdefault(season, set()).update((home, away))
        result.append({'game_id': gid, 'season': season, 'phase': row['game_type'], 'week': row.get('week'), 'kickoff': start.isoformat(),
                       'home_team': home, 'away_team': away, 'home_score': None if pending else int(scores[0]),
                       'away_score': None if pending else int(scores[1]),
                       'neutral': row['location'] == 'Neutral'})
    if set(season_teams) != set(range(start_season, end_season + 1)):
        raise SourceError('One or more requested Elo seasons are missing.')
    initial_teams = season_teams[start_season]
    if len(initial_teams) != 32 or any(teams != initial_teams for teams in season_teams.values()):
        raise SourceError('Elo history does not contain the same 32 verified franchises in each requested season.')
    if as_of is not None and initial_teams != set(TEAM_NAMES):
        raise SourceError('Elo history contains unrecognized NFL franchises.')
    return sorted(result, key=lambda game: (game['season'], game['kickoff'], game['game_id']))


def replay_elo(games, config, *, teams=None, freeze_dates=False):
    """Replay the approved model; optional UTC date batches freeze margin forecasts."""
    teams = sorted(teams if teams is not None else {game[key] for game in games for key in ('home_team', 'away_team')})
    ratings = dict.fromkeys(teams, CENTER)
    season, logs, openings = None, [], {}
    for _, batch in groupby(games, key=lambda g: (g['season'], g['kickoff'][:10]) if freeze_dates else g['game_id']):
        batch = list(batch)
        game = batch[0]
        if game['season'] != season:
            if season is not None:
                ratings = {team: CENTER + (rating - CENTER) * config.offseason_retention
                           for team, rating in ratings.items()}
            season = game['season']
            openings[season] = ratings.copy()
        frozen = ratings.copy()
        for game in batch:
            home, away = game['home_team'], game['away_team']
            home_before, away_before = frozen[home], frozen[away]
            advantage = 0.0 if game['neutral'] else config.home_advantage
            difference = home_before - away_before + advantage
            expectation = expected_score(difference)
            actual = 1.0 if game['home_score'] > game['away_score'] else 0.0 if game['home_score'] < game['away_score'] else 0.5
            multiplier = margin_multiplier(game['home_score'], game['away_score'], difference)
            change = config.k * multiplier * (actual - expectation)
            ratings[home] += change
            ratings[away] -= change
            if not all(math.isfinite(rating) for rating in (ratings[home], ratings[away])):
                raise SourceError('Elo replay produced non-finite ratings; settings require review.')
            logs.append({**game, 'home_rating_before': home_before, 'away_rating_before': away_before,
                         'home_advantage': advantage, 'home_expected_score': expectation,
                         'away_expected_score': 1 - expectation, 'home_result': actual,
                         'margin_multiplier': multiplier, 'home_change': change, 'away_change': -change,
                         'home_rating_after': ratings[home], 'away_rating_after': ratings[away]})
    return {'config': asdict(config), 'ratings': ratings, 'season_openings': openings, 'games': logs,
            'probability_note': 'Elo expected score: P(win) + 0.5 × P(tie). No separate tie model or spread-cover probability.'}


def calculate_elo(season, rows, *, now=None):
    """Recompute from saved results; repeated reads and corrections never double count."""
    now = now or datetime.now(timezone.utc)
    schedule = prepare_elo_history(rows, end_season=season, as_of=now)
    completed = [game for game in schedule if game['home_score'] is not None]
    replay = replay_elo(completed, APPROVED_CONFIG, teams=TEAM_NAMES)
    ratings = replay['ratings'] or dict.fromkeys(TEAM_NAMES, CENTER)
    openings = replay['season_openings'].get(season)
    if openings is None:
        # Before the first result of a season, apply that offseason exactly once.
        ratings = {team: CENTER + (value - CENTER) * APPROVED_CONFIG.offseason_retention
                   for team, value in ratings.items()}
        openings = ratings.copy()
    logs = [game for game in replay['games'] if game['season'] == season]
    by_id = {game['game_id']: game for game in logs}
    teams = []
    for team in sorted(ratings, key=lambda code: (-ratings[code], code)):
        team_logs = []
        for game in logs:
            if team not in (game['home_team'], game['away_team']):
                continue
            side = 'home' if team == game['home_team'] else 'away'
            other = 'away' if side == 'home' else 'home'
            team_logs.append({**game, 'opponent': game[f'{other}_team'], 'side': side,
                              'rating_before': game[f'{side}_rating_before'], 'rating_after': game[f'{side}_rating_after'],
                              'change': game[f'{side}_change'], 'expected_score': game[f'{side}_expected_score'],
                              'result': game['home_result'] if side == 'home' else 1 - game['home_result']})
        teams.append({'team': team, 'rating': ratings[team],
                      'rank': 1 + sum(value > ratings[team] for value in ratings.values()),
                      'season_start_rating': openings[team], 'season_change': ratings[team] - openings[team],
                      'last_change': team_logs[-1]['change'] if team_logs else None,
                      'games_played': len(team_logs), 'games': team_logs})
    matchups, pending_ids = [], []
    for game in schedule:
        if game['season'] != season:
            continue
        if game['game_id'] in by_id:
            matchups.append({**by_id[game['game_id']], 'status': 'completed', 'basis': 'pregame_ratings'})
            continue
        started = datetime.fromisoformat(game['kickoff']) <= now
        if started:
            pending_ids.append(game['game_id'])
        advantage = 0 if game['neutral'] else APPROVED_CONFIG.home_advantage
        expectation = expected_score(ratings[game['home_team']] - ratings[game['away_team']] + advantage)
        matchups.append({**game, 'status': 'awaiting_score' if started else 'upcoming',
                         'basis': 'latest_ratings', 'home_rating': ratings[game['home_team']],
                         'away_rating': ratings[game['away_team']], 'home_advantage': advantage,
                         'home_expected_score': expectation, 'away_expected_score': 1 - expectation})
    warnings = [SCORE_NOTICE]
    if pending_ids:
        warnings.append(f'{len(pending_ids)} started games have no published scores and are excluded from rating updates.')
    return {'season': season, 'start_season': 2002, 'config': replay['config'],
            'probability_note': replay['probability_note'], 'teams': teams, 'matchups': matchups,
            'league': {'mean': sum(ratings.values()) / len(ratings), 'median': median(ratings.values()),
                       'direction': 'Higher is better', 'teams': len(ratings)},
            'replayed_games': len(completed), 'latest_result_kickoff': completed[-1]['kickoff'] if completed else None,
            'awaiting_score_game_ids': pending_ids, 'warnings': warnings}
