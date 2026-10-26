from dataclasses import dataclass, field
import ssl
import certifi
from datetime import datetime, timezone
from http.client import HTTPException
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SourceError(ValueError):
    """A source could not be downloaded or safely interpreted."""


class RateLimitError(SourceError):
    def __init__(self, retry_after=None):
        super().__init__('Source returned HTTP 429. Rate limited; saved data retained.')
        self.retry_after = retry_after


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Resource:
    body: bytes
    url: str
    fetched_at: str
    last_modified: str | None = None


@dataclass
class SourceData:
    rows: list[dict[str, Any]]
    url: str
    fetched_at: str
    source_updated_at: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


Fetcher = Callable[[str], Resource]


def fetch_public(url: str) -> Resource:
    """Fetch a public URL chosen by a source reader; no account credentials."""
    request = Request(url, headers={"User-Agent": "Deck/0.1 (personal research)"})
    try:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        with urlopen(request, timeout=30, context=context) as response:
            return Resource(
                body=response.read(), url=url, fetched_at=utc_now(),
                last_modified=response.headers.get("Last-Modified"),
            )
    except HTTPError as error:
        if error.code == 429:
            retry = error.headers.get('Retry-After') if error.headers else None
            try:
                delay = max(0, int(retry))
            except (TypeError, ValueError):
                try:
                    delay = max(0, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    delay = None
            raise RateLimitError(delay) from error
        raise SourceError(f"Source returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError, HTTPException) as error:
        raise SourceError("Source could not be reached. Try refreshing again.") from error
