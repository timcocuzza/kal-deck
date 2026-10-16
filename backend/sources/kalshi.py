from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import quote, urlencode

from .common import Fetcher, SourceData, SourceError, fetch_public


BASE = "https://external-api.kalshi.com/trade-api/v2"


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Z0-9_-]+", value):
        raise SourceError("Invalid Kalshi identifier.")
    return quote(value, safe="")


def _json_resource(url: str, fetch: Fetcher):
    resource = fetch(url)
    try:
        data = json.loads(resource.body)
    except (ValueError, UnicodeError) as error:
        raise SourceError("Kalshi returned unreadable JSON.") from error
    if not isinstance(data, dict):
        raise SourceError("Kalshi response format changed.")
    return resource, data


def load_markets(series: str, fetch: Fetcher = fetch_public) -> SourceData:
    _identifier(series)
    rows = []
    seen_tickers: set[str] = set()
    seen_cursors: set[str] = set()
    cursor = ""
    initial_url = ""
    while True:
        params = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        url = f"{BASE}/markets?{urlencode(params)}"
        initial_url = initial_url or url
        resource, data = _json_resource(url, fetch)
        page = data.get("markets")
        if not isinstance(page, list):
            raise SourceError("Kalshi markets list is missing.")
        for market in page:
            if not isinstance(market, dict) or not all(
                isinstance(market.get(key), str) and market[key]
                for key in ("ticker", "event_ticker", "market_type")
            ):
                raise SourceError("Kalshi supplied an incomplete market record.")
            if not market["event_ticker"].startswith(series + "-"):
                raise SourceError("Kalshi supplied a market from a different series.")
            if market["ticker"] not in seen_tickers:
                seen_tickers.add(market["ticker"])
                rows.append(market)
        cursor = data.get("cursor", "")
        if not isinstance(cursor, str):
            raise SourceError("Kalshi pagination format changed.")
        if not cursor:
            break
        if cursor in seen_cursors:
            raise SourceError("Kalshi repeated a pagination cursor; snapshot is incomplete.")
        seen_cursors.add(cursor)
    return SourceData(rows, initial_url, resource.fetched_at, context={"series": series})


def load_history(series: str, ticker: str, start: int, end: int, interval: int,
                 fetch: Fetcher = fetch_public) -> SourceData:
    if start < 0 or end <= start or interval not in (1, 60, 1440):
        raise SourceError("Invalid history window or interval.")
    if not ticker.startswith(series + "-"):
        raise SourceError("Market does not belong to the requested series.")
    path = f"/series/{_identifier(series)}/markets/{_identifier(ticker)}/candlesticks"
    url = BASE + path + "?" + urlencode({"start_ts": start, "end_ts": end, "period_interval": interval})
    resource, data = _json_resource(url, fetch)
    rows = data.get("candlesticks")
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or type(row.get("end_period_ts")) is not int for row in rows
    ):
        raise SourceError("Kalshi history response format changed.")
    if data.get("ticker") != ticker:
        raise SourceError("Kalshi returned history for a different contract.")
    times = [row["end_period_ts"] for row in rows]
    if len(set(times)) != len(times):
        raise SourceError("Kalshi returned duplicate history timestamps.")
    if any(timestamp < start or timestamp > end for timestamp in times):
        raise SourceError("Kalshi returned history outside the requested window.")
    return SourceData(rows, url, resource.fetched_at, context={
        "ticker": ticker, "series": series, "start_ts": start, "end_ts": end, "interval_minutes": interval,
    })


def history_points(rows: list[dict]) -> list[dict]:
    """Use only the supplied closing quotes; missing periods stay absent."""
    points = []
    for row in sorted(rows, key=lambda item: item["end_period_ts"]):
        bid = row.get("yes_bid")
        ask = row.get("yes_ask")
        bid = bid.get("close_dollars") if isinstance(bid, dict) else None
        ask = ask.get("close_dollars") if isinstance(ask, dict) else None
        midpoint = quote_midpoint({"market_type": "binary", "yes_bid_dollars": bid, "yes_ask_dollars": ask})
        points.append({
            "timestamp": row["end_period_ts"],
            "midpoint": float(midpoint) if midpoint is not None else None,
            "bid": str(bid) if midpoint is not None else None,
            "ask": str(ask) if midpoint is not None else None,
        })
    return points


def quote_midpoint(market: dict) -> Decimal | None:
    """Indicative YES midpoint. Preserve unavailable quotes as unavailable."""
    if market.get("market_type") != "binary":
        return None
    try:
        bid = Decimal(market["yes_bid_dollars"])
        ask = Decimal(market["yes_ask_dollars"])
        if bid.is_finite() and ask.is_finite() and 0 < bid <= ask < 1:
            return (bid + ask) / 2
    except (KeyError, TypeError, InvalidOperation):
        pass
    return None


def select_default_spread(markets: list[dict]) -> dict | None:
    candidates = []
    for market in markets:
        midpoint = quote_midpoint(market)
        if midpoint is None:
            continue
        gap = Decimal(market["yes_ask_dollars"]) - Decimal(market["yes_bid_dollars"])
        try:
            volume = Decimal(market.get("volume_fp") or "0")
            if not volume.is_finite() or volume < 0:
                volume = Decimal(0)
        except (InvalidOperation, TypeError):
            volume = Decimal(0)
        candidates.append((abs(midpoint - Decimal("0.5")), gap, -volume, market["ticker"], market))
    return min(candidates, key=lambda item: item[:4])[-1] if candidates else None
