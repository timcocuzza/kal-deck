import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from backend.security import PrivateAPIResponses, allowed_origins, validate_write_origin


def request(origin=None, site=None, method='POST', host='deck.getwellsedge.com'):
    headers = [(b'host', host.encode())]
    if origin is not None:
        headers.append((b'origin', origin.encode()))
    if site:
        headers.append((b'sec-fetch-site', site.encode()))
    return Request({'type': 'http', 'method': method, 'headers': headers})


class OriginTests(unittest.TestCase):
    def test_hosted_writes_require_exact_origin_including_sibling_subdomains(self):
        with patch.dict(os.environ, {'DECK_PUBLIC_ORIGIN': 'https://deck.getwellsedge.com'}):
            asyncio.run(validate_write_origin(request('https://deck.getwellsedge.com')))
            for origin in (None, 'null', 'https://getwellsedge.com', 'https://evil.example',
                           'http://deck.getwellsedge.com', 'http://localhost:5173'):
                with self.subTest(origin=origin), self.assertRaises(HTTPException) as caught:
                    asyncio.run(validate_write_origin(request(origin)))
                self.assertEqual(caught.exception.status_code, 403)

    def test_cross_site_and_host_header_cannot_authorize_writes(self):
        with patch.dict(os.environ, {}, clear=True):
            for req in (request('http://evil.example:8000', host='evil.example:8000'),
                        request('http://localhost:8000', site='cross-site')):
                with self.assertRaises(HTTPException):
                    asyncio.run(validate_write_origin(req))
            asyncio.run(validate_write_origin(request('http://localhost:5173')))
            asyncio.run(validate_write_origin(request()))

    def test_https_configuration_rejects_paths_credentials_and_queries(self):
        for value in ('http://deck.getwellsedge.com', 'https://deck.getwellsedge.com/',
                      'https://user:pass@deck.getwellsedge.com', 'https://deck.getwellsedge.com?x=1'):
            with patch.dict(os.environ, {'DECK_PUBLIC_ORIGIN': value}), self.assertRaises(RuntimeError):
                allowed_origins()


class CacheTests(unittest.TestCase):
    def test_private_headers_apply_to_reads_writes_and_rejected_api_responses(self):
        async def exercise(status):
            sent = []
            async def app(scope, receive, send):
                await send({'type': 'http.response.start', 'status': status,
                            'headers': [(b'cache-control', b'public')]})
                await send({'type': 'http.response.body', 'body': b'{}'})
            async def receive():
                return {'type': 'http.request'}
            async def send(message):
                sent.append(message)
            await PrivateAPIResponses(app)({'type': 'http', 'path': '/api/tracker'}, receive, send)
            return dict(sent[0]['headers'])
        for status in (200, 403, 422):
            headers = asyncio.run(exercise(status))
            self.assertEqual(headers[b'cache-control'], b'no-store')
            self.assertEqual(headers[b'x-content-type-options'], b'nosniff')


class HostedRouteTests(unittest.TestCase):
    def test_refresh_origin_is_enforced_before_any_upstream_work(self):
        from backend import app as api
        from test_watchlist import request as api_request
        with patch.dict(os.environ, {'DECK_PUBLIC_ORIGIN': 'https://deck.getwellsedge.com'}):
            with patch.object(api.refresh_service, 'refresh', return_value={'status': 'ready'}) as refresh:
                path = '/api/sources/spreads/refresh?season=2026'
                for origin in (None, 'https://getwellsedge.com', 'https://attacker.example'):
                    self.assertEqual(api_request('POST', path, origin=origin)[0], 403)
                refresh.assert_not_called()
                self.assertEqual(api_request('POST', path, origin='https://deck.getwellsedge.com')[0], 200)
                refresh.assert_called_once_with('spreads', 2026)
