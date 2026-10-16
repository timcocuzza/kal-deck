from dataclasses import dataclass
from threading import Lock

from .sources.common import Fetcher, SourceError, fetch_public
from .sources.kalshi import load_markets
from .sources.kalshi_metadata import load_games, load_teams, load_players
from .sources.nflverse import load_dataset
from .sources.pages import load_coverage, load_injuries
from .storage import SnapshotStore


@dataclass(frozen=True)
class SourceSpec:
    name: str
    label: str
    provider: str
    dataset: str
    seasonal: bool = False

    def key(self, season: int) -> str:
        return f"{self.name}:{season}" if self.seasonal else self.name

    def load(self, season: int, fetch: Fetcher, store: SnapshotStore):
        if self.provider == "nflverse":
            return load_dataset(self.dataset, season, fetch)
        if self.provider == "Kalshi":
            if self.dataset == "game_metadata":
                spreads = store.read("spreads")
                if spreads is None:
                    raise SourceError("Refresh Spread contracts before Kalshi game identities.")
                return load_games(season, [row['event_ticker'] for row in spreads.rows], fetch)
            if self.dataset == "team_metadata":
                return load_teams(fetch)
            if self.dataset == "player_metadata":
                return load_players(fetch)
            return load_markets(self.dataset, fetch)
        if self.provider == "Sharp Football":
            return load_coverage(fetch)
        return load_injuries(fetch)


SOURCES = [
    SourceSpec("schedule", "Game schedule", "nflverse", "schedule", True),
    SourceSpec("elo_history", "Elo game history", "nflverse", "elo_history", True),
    SourceSpec("team_stats", "Team statistics", "nflverse", "team_stats", True),
    SourceSpec("player_stats", "Player game logs", "nflverse", "player_stats", True),
    SourceSpec("play_by_play", "Ranking inputs", "nflverse", "play_by_play", True),
    SourceSpec("depth_charts", "Depth charts", "nflverse", "depth_charts", True),
    SourceSpec("ftn_charting", "Blitz charting", "nflverse", "ftn_charting", True),
    SourceSpec("coverage", "Man / zone coverage", "Sharp Football", "coverage"),
    SourceSpec("injuries", "Current injury reports", "NFL", "injuries"),
    SourceSpec("kalshi_teams", "Kalshi team identities", "Kalshi", "team_metadata"),
    SourceSpec("spreads", "Spread contracts", "Kalshi", "KXNFLSPREAD"),
    SourceSpec("kalshi_games", "Kalshi game identities", "Kalshi", "game_metadata", True),
    SourceSpec("kalshi_players", "Kalshi player identities", "Kalshi", "player_metadata"),
    SourceSpec("receiving_yards", "Receiving yards props", "Kalshi", "KXNFLRECYDS"),
    SourceSpec("rushing_yards", "Rushing yards props", "Kalshi", "KXNFLRSHYDS"),
    SourceSpec("passing_yards", "Passing yards props", "Kalshi", "KXNFLPASSYDS"),
    SourceSpec("receptions", "Receptions props", "Kalshi", "KXNFLREC"),
    SourceSpec("passing_tds", "Passing touchdown props", "Kalshi", "KXNFLPASSTDS"),
    SourceSpec("passing_attempts", "Passing attempts props", "Kalshi", "KXNFLPASSATT"),
    SourceSpec("passing_completions", "Passing completions props", "Kalshi", "KXNFLPASSCOMP"),
    SourceSpec("passing_interceptions", "Interceptions thrown props", "Kalshi", "KXNFLPASSINT"),
    SourceSpec("rushing_attempts", "Rushing attempts props", "Kalshi", "KXNFLRSHATT"),
    SourceSpec("rushing_receiving_yards", "Combined rushing / receiving yards props", "Kalshi", "KXNFLRRYDS"),
]
BY_NAME = {source.name: source for source in SOURCES}


class RefreshService:
    def __init__(self, store: SnapshotStore, fetch: Fetcher = fetch_public):
        self.store = store
        self.fetch = fetch
        self.locks = {source.name: Lock() for source in SOURCES}

    def status(self, name: str, season: int) -> dict:
        source = BY_NAME[name]
        return {
            "name": source.name, "label": source.label, "provider": source.provider,
            "season": season if source.seasonal else None,
            **self.store.status(source.key(season)),
        }

    def refresh(self, name: str, season: int) -> dict:
        source = BY_NAME[name]
        lock = self.locks[name]
        if not lock.acquire(blocking=False):
            raise SourceError("This source is already refreshing.")
        try:
            try:
                result = source.load(season, self.fetch, self.store)
                self.store.save(source.key(season), result)
            except SourceError as error:
                self.store.record_failure(source.key(season), str(error))
            return self.status(name, season)
        finally:
            lock.release()
