"""College performance rating core, independently checked against the frozen experiment.

Internal units are points of strength, not conventional Elo probabilities.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import groupby
import math
from statistics import mean

CONFIG = dict(family='clip', alpha=0.2, home=2, cap=28, retention=0.4)
DIVISIONS = {'fbs', 'fcs'}

@dataclass(frozen=True)
class Game:
    id: str
    season: int
    week: int
    kickoff: str
    day: str
    home: str
    away: str
    home_name: str
    away_name: str
    home_div: str
    away_div: str
    home_score: int
    away_score: int
    neutral: bool
    phase: str

    @property
    def margin(self):
        return self.home_score - self.away_score

    @property
    def matchup(self):
        return '-'.join(sorted((self.home_div, self.away_div)))

def bounded_residual(error, family, cap):
    if family == 'tanh':
        return cap * math.tanh(error / cap)
    if family == 'clip':
        return max(-cap, min(cap, error))
    if family == 'linear':
        return error
    raise ValueError('Unknown performance family')

def logistic(difference):
    tail = math.exp(-abs(difference) * math.log(10) / 400)
    return 1 / (1 + tail) if difference >= 0 else tail / (1 + tail)

def replay(games, config, *, reverse_day=False):
    """Past-only division centers, season regression and simultaneous date batches."""
    ratings, divisions, last_season = {}, {}, {}
    current_season, active, centers, season_games = None, set(), {'fbs': 0.0, 'fcs': 0.0}, Counter()
    logs = []
    for (season, day), batch_iter in groupby(games, key=lambda g: (g.season, g.day)):
        batch = list(batch_iter)
        if reverse_day:
            batch.reverse()
        if season != current_season:
            if current_season is not None:
                for division in DIVISIONS:
                    values = [ratings[t] for t in sorted(active) if divisions[t] == division]
                    if values:
                        centers[division] = mean(values)
            current_season, active, season_games = season, set(), Counter()
        for game in batch:
            for tid, div in ((game.home, game.home_div), (game.away, game.away_div)):
                if tid not in ratings:
                    ratings[tid], divisions[tid] = centers[div], div
                elif last_season[tid] != season:
                    # Retain the old division for regression on a transition. A
                    # move to FBS never injects a free FBS-center rating increase.
                    center = centers[divisions[tid]]
                    ratings[tid] = center + config['retention'] ** (season - last_season[tid]) * (ratings[tid] - center)
                last_season[tid] = season
                divisions[tid] = div
                active.add(tid)
        changes = defaultdict(float)
        for game in batch:
            before_home, before_away = ratings[game.home], ratings[game.away]
            difference = before_home - before_away + (0 if game.neutral else config['home'])
            actual = 1.0 if game.margin > 0 else 0.0 if game.margin < 0 else 0.5
            if config['family'] in ('elo', 'nfl_margin'):
                probability = logistic(difference)
                multiplier = 1.0
                if config['family'] == 'nfl_margin':
                    winner_difference = difference if game.margin > 0 else -difference
                    denominator = 2.2 + winner_difference * 0.001
                    if denominator <= 0:
                        raise ValueError('NFL margin multiplier outside valid range')
                    multiplier = math.log(abs(game.margin) + 1) * 2.2 / denominator if game.margin else math.log(2) * 2.2
                change = config['alpha'] * multiplier * (actual - probability)
            else:
                change = config['alpha'] * bounded_residual(game.margin - difference, config['family'], config['cap'])
            changes[game.home] += change
            changes[game.away] -= change
            logs.append({'game': game, 'raw_benchmark': difference, 'benchmark': difference,
                         'home_before': before_home, 'away_before': before_away, 'home_change': change,
                         'home_after': before_home + change, 'away_after': before_away - change,
                         'home_games_before': season_games[game.home], 'away_games_before': season_games[game.away],
                         'division_centers': centers.copy()})
        for team, change in changes.items():
            ratings[team] += change
            season_games[team] += 1
            if not math.isfinite(ratings[team]):
                raise ValueError('Non-finite rating')
    return sorted(logs, key=lambda row: (row['game'].day, row['game'].id))
