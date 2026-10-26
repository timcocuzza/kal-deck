"""Bounded public-market requests with persistent cache and rate-limit cooldown."""
from datetime import datetime, timezone
import hashlib
import json
import time
from urllib.parse import urlsplit

from .common import RateLimitError, Resource, SourceData, SourceError


class CollegeMarketFetch:
    def __init__(self, fetch, store, *, clock=time.time, sleep=time.sleep):
        self.fetch, self.store, self.clock, self.sleep = fetch, store, clock, sleep
        self.last_request = None

    def __call__(self, url):
        path = urlsplit(url).path
        ttl = 86400 if path.endswith('/structured_targets') else 300 if path.endswith('/milestones') else 15
        key = 'cfb_http:' + hashlib.sha256(url.encode()).hexdigest()
        cached = self.store.read(key)
        now = self.clock()
        if cached and -.001 <= now - datetime.fromisoformat(cached.fetched_at).timestamp() < ttl:
            row = cached.rows[0]
            return Resource(row['body'].encode(), url, cached.fetched_at, row['last_modified'])
        cooldown = self.store.read('cfb_http:cooldown')
        if cooldown and cooldown.rows[0]['until'] > now:
            raise SourceError('College markets are cooling down after a rate limit. Try again after '
                              + datetime.fromtimestamp(cooldown.rows[0]['until'], timezone.utc).isoformat() + '.')
        for attempt in range(3):
            if self.last_request is not None:
                self.sleep(max(0, .35 - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            try:
                resource = self.fetch(url)
            except RateLimitError as error:
                delay = error.retry_after if error.retry_after is not None else 2 ** attempt
                if attempt == 2 or delay > 5:
                    until = self.clock() + max(delay, 30)
                    self.store.save('cfb_http:cooldown', SourceData([{'until': until}], url,
                                    datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()))
                    raise
                self.sleep(delay)
                continue
            # Do not cache an unreadable response. Source readers still validate
            # the identities and contracts before replacing the coherent report.
            try:
                payload = json.loads(resource.body)
                if not isinstance(payload, dict):
                    raise ValueError('Expected an object')
            except (ValueError, UnicodeError) as error:
                raise SourceError('College markets returned unreadable JSON.') from error
            self.store.save(key, SourceData([{'body': resource.body.decode(), 'last_modified': resource.last_modified}],
                                           url, resource.fetched_at))
            return resource
        raise SourceError('College market retries exhausted.')
