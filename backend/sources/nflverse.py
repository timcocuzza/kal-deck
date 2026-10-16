import csv
import gzip
import io
import zlib
from datetime import datetime

from .common import Fetcher, SourceData, SourceError, fetch_public


RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
SCHEDULE = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
DATASETS = {
    "team_stats": ("stats_team/stats_team_week_{season}.csv.gz", {
        "season", "week", "season_type", "game_id", "team", "opponent_team",
        "passing_yards", "rushing_yards", "sacks_suffered", "def_sacks",
        "completions", "attempts", "passing_tds", "passing_interceptions", "carries", "rushing_tds",
        "receiving_yards", "targets", "receptions", "receiving_tds",
    }),
    "player_stats": ("stats_player/stats_player_week_{season}.csv.gz", {
        "season", "week", "season_type", "game_id", "player_id", "player_display_name",
        "team", "opponent_team", "passing_yards", "rushing_yards", "receiving_yards",
        "position", "receptions", "passing_tds", "attempts", "completions", "passing_interceptions", "carries",
        "targets", "receiving_tds", "rushing_tds",
    }),
    "play_by_play": ("pbp/play_by_play_{season}.csv.gz", {
        "season", "week", "season_type", "game_id", "play_id", "posteam", "defteam",
        "epa", "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike", "success",
        "sack", "play_type", "rush_attempt", "two_point_attempt", "pass", "rush",
        "rusher_player_id", "rushing_yards",
    }),
    "depth_charts": ("depth_charts/depth_charts_{season}.csv.gz", {
        "dt", "team", "player_name", "gsis_id", "espn_id", "pos_abb", "pos_rank",
    }),
    "ftn_charting": ("ftn_charting/ftn_charting_{season}.csv", {
        "season", "week", "nflverse_game_id", "nflverse_play_id", "n_blitzers", "n_pass_rushers",
    }),
}


def load_dataset(dataset: str, season: int, fetch: Fetcher = fetch_public) -> SourceData:
    if not 1999 <= season <= 2100:
        raise SourceError("Invalid NFL season.")
    if dataset in ("schedule", "elo_history"):
        url = SCHEDULE
        required = {"season", "week", "game_id", "game_type", "gameday", "gametime", "home_team", "away_team", "home_score", "away_score"}
        if dataset == 'elo_history':
            required.add('location')
    elif dataset in DATASETS:
        template, required = DATASETS[dataset]
        url = f"{RELEASES}/{template.format(season=season)}"
    else:
        raise SourceError("Unknown nflverse dataset.")
    resource = fetch(url)
    try:
        body = gzip.decompress(resource.body) if url.endswith(".gz") else resource.body
        reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        if not required.issubset(reader.fieldnames or []):
            raise SourceError("Source columns changed; the previous snapshot was not replaced.")
        rows = []
        latest_depth: dict[str, str] = {}
        depth_rows: dict[str, list[dict[str, str]]] = {}
        for row in reader:
            if None in row or any(row.get(key) is None for key in required):
                raise SourceError("Incomplete CSV row received.")
            if dataset == "schedule":
                if row["season"] != str(season):
                    continue
            elif dataset == 'elo_history':
                if not row['season'].isdigit():
                    raise SourceError('Elo history has an invalid season.')
                if not 2002 <= int(row['season']) <= season or row['game_type'] == 'PRE':
                    continue
            elif dataset != "depth_charts" and row["season"] != str(season):
                raise SourceError("Source returned a different season.")
            if dataset == "depth_charts":
                team, updated = row["team"], row["dt"]
                if not team or not updated:
                    raise SourceError("Depth chart is missing its team or snapshot date.")
                if updated > latest_depth.get(team, ""):
                    latest_depth[team] = updated
                    depth_rows[team] = []
                if updated == latest_depth[team]:
                    depth_rows[team].append(row)
            else:
                rows.append(row)
        if dataset == "depth_charts":
            rows = [row for team in sorted(depth_rows) for row in depth_rows[team]]
        if not rows:
            raise SourceError(f"No {season} records were supplied for this dataset.")
    except (UnicodeError, csv.Error, gzip.BadGzipFile, EOFError, zlib.error) as error:
        raise SourceError("Source did not return a readable CSV file.") from error
    warnings = []
    if dataset == "ftn_charting":
        warnings.append("FTN charting via nflverse; attribution: FTN Data.")
    context = {"season": season, "dataset": dataset}
    if dataset == 'elo_history':
        from ..elo import calculate_elo, SCORE_NOTICE
        # Validate the complete replay before replacing a usable snapshot.
        calculate_elo(season, rows, now=datetime.fromisoformat(resource.fetched_at))
        context['start_season'] = 2002
        warnings.append(SCORE_NOTICE)
    if latest_depth:
        context["team_snapshot_dates"] = latest_depth
    return SourceData(
        rows, url, resource.fetched_at, resource.last_modified, context, warnings,
    )
