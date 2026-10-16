"""Extract published tables without evaluating webpage scripts."""

from dataclasses import dataclass, field
from html.parser import HTMLParser
import math
import json
import re

from .common import Fetcher, SourceData, SourceError, fetch_public


COVERAGE_URL = "https://www.sharpfootballanalysis.com/stats-nfl/nfl-coverage-schemes/"
INJURIES_URL = "https://www.nfl.com/injuries/"


@dataclass
class Table:
    label: str
    rows: list[list[str]] = field(default_factory=list)


class PublishedTables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self.table: Table | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.label = ""
        self.label_parts: list[str] | None = None
        self.label_depth = 0
        self.meta: dict[str, str] = {}
        self.text: list[str] = []
        self.ignore_depth = 0
        self.structured_parts: list[str] | None = None
        self.structured: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.structured_parts = []
        if tag in ("script", "style"):
            self.ignore_depth += 1
        if self.ignore_depth:
            return
        if tag == "meta":
            self.meta[attrs.get("property", attrs.get("name", ""))] = attrs.get("content", "")
        if tag == "div":
            if self.label_parts is not None:
                self.label_depth += 1
            elif "d3-o-section-sub-title" in attrs.get("class", "").split():
                self.label_parts = []
                self.label_depth = 1
        if tag == "table":
            if self.table is not None:
                raise SourceError("Nested source table is not supported.")
            self.table = Table(self.label)
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.structured_parts is not None:
            self.structured_parts.append(data)
        if self.ignore_depth:
            return
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)
        if self.label_parts is not None:
            self.label_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.structured_parts is not None:
            try:
                data = json.loads("".join(self.structured_parts))
                if isinstance(data, dict):
                    self.structured.append(data)
            except ValueError:
                pass  # Optional publication metadata; never execute page scripts.
            self.structured_parts = None
        if tag in ("script", "style"):
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth:
            return
        if tag == "div" and self.label_parts is not None:
            self.label_depth -= 1
            if self.label_depth == 0:
                self.label = " ".join("".join(self.label_parts).split())
                self.label_parts = None
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _page(url: str, fetch: Fetcher):
    resource = fetch(url)
    parser = PublishedTables()
    try:
        parser.feed(resource.body.decode("utf-8"))
        parser.close()
    except UnicodeError as error:
        raise SourceError("Source page could not be decoded.") from error
    if parser.table is not None:
        raise SourceError("Source page ended inside a table.")
    return resource, parser


def load_coverage(fetch: Fetcher = fetch_public) -> SourceData:
    resource, page = _page(COVERAGE_URL, fetch)
    tables = [t for t in page.tables if t.rows and {"Team", "Man Rate", "Zone Rate"}.issubset(t.rows[0])]
    if len(tables) != 1:
        raise SourceError("Coverage table is missing or its layout changed.")
    table = tables[0]
    rows = []
    teams = set()
    for cells in table.rows[1:]:
        if len(cells) != len(table.rows[0]):
            raise SourceError("Coverage table has an incomplete row.")
        raw = dict(zip(table.rows[0], cells))
        team = raw["Team"]
        if not team or team in teams:
            raise SourceError("Coverage table has a missing or duplicate team.")
        try:
            man, zone = (float(raw[key].rstrip("%")) for key in ("Man Rate", "Zone Rate"))
        except ValueError as error:
            raise SourceError("Coverage table has missing or invalid percentages.") from error
        if any(not math.isfinite(value) or not 0 <= value <= 100 for value in (man, zone)):
            raise SourceError("Coverage percentage is out of range.")
        teams.add(team)
        rows.append({"team_name": team, "man_percentage": man, "zone_percentage": zone})
    if len(teams) != 32:
        raise SourceError("Coverage table does not contain all 32 teams.")
    date = page.meta.get("article:modified_time") or page.meta.get("article:published_time")
    if not date:
        article = next((item for item in page.structured if item.get("@type") == "NewsArticle"), {})
        date = article.get("dateModified") or article.get("datePublished")
        if not isinstance(date, str):
            date = None
    return SourceData(rows, COVERAGE_URL, resource.fetched_at, date, warnings=[
        "The page does not explicitly state its statistical cutoff or charting denominator.",
        "Man and zone percentages are preserved as published and may not total 100%.",
    ])


def load_injuries(fetch: Fetcher = fetch_public) -> SourceData:
    resource, page = _page(INJURIES_URL, fetch)
    text = " ".join(page.text)
    season_match = re.search(r"\b(20\d{2})\s+NFL Injury Report", text)
    week_match = re.search(r"Injuries\s*-\s*WEEK\s+(\d+)", text, re.IGNORECASE)
    if not season_match or not week_match:
        raise SourceError("The injury report's season or week could not be verified.")
    headers = ["Player", "Position", "Injuries", "Practice Status", "Game Status"]
    tables = [t for t in page.tables if t.rows and t.rows[0] == headers]
    if not tables:
        raise SourceError("No injury report tables were found; this is not a clean bill of health.")
    rows = []
    reported_teams = []
    for table in tables:
        if not table.label or table.label in reported_teams:
            raise SourceError("Injury report team labels are missing or duplicated.")
        reported_teams.append(table.label)
        seen_players = set()
        for cells in table.rows[1:]:
            if len(cells) != 5 or not cells[0] or cells[0] in seen_players:
                raise SourceError("Injury report contains an incomplete or duplicate player row.")
            seen_players.add(cells[0])
            rows.append({
                "team_name": table.label, "player_name": cells[0], "position": cells[1],
                "injury": cells[2] or None, "practice_status": cells[3] or None,
                "game_status": cells[4] or None,
            })
    return SourceData(rows, INJURIES_URL, resource.fetched_at, resource.last_modified, {
        "season": int(season_match[1]), "week": int(week_match[1]),
        "reported_teams": reported_teams,
    }, ["Missing reports and blank game status do not mean a player is healthy."])
