"""Browser write-origin checks. These are not authentication or authorization."""

import os
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def allowed_origins() -> set[str]:
    desktop = os.environ.get('DECK_DESKTOP_ORIGIN')
    if desktop:
        parsed = urlsplit(desktop)
        if (not os.environ.get('DECK_DESKTOP_TOKEN') or parsed.scheme != 'http'
                or parsed.hostname != '127.0.0.1' or not parsed.port
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise RuntimeError('Invalid private desktop origin.')
        return {desktop}
    origin = os.environ.get('DECK_PUBLIC_ORIGIN')
    if origin:
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise RuntimeError('DECK_PUBLIC_ORIGIN must be an HTTPS origin without a trailing slash.')
        return {origin}
    return {f'http://{host}:{port}' for host in ('localhost', '127.0.0.1') for port in (8000, 5173)}


async def validate_write_origin(request: Request):
    if request.method in {'GET', 'HEAD', 'OPTIONS'}:
        return
    origin = request.headers.get('origin')
    # Local command-line tools have no Origin. Hosted browser writes must have one.
    if (request.headers.get('sec-fetch-site') == 'cross-site'
            or (origin is None and os.environ.get('DECK_PUBLIC_ORIGIN'))
            or (origin is not None and origin not in allowed_origins())):
        raise HTTPException(status_code=403, detail='Changes must come from the Deck app.')


class DesktopAccess:
    """Only the owning desktop process may access its private local service."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = os.environ.get('DECK_DESKTOP_TOKEN')
        if not token or scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        expected = os.environ.get('DECK_DESKTOP_ORIGIN', '')
        supplied = headers.get(b'x-deck-desktop-token', b'')
        status = 0
        if not secrets.compare_digest(supplied, token.encode()):
            status = 401
        elif not expected or headers.get(b'host', b'').decode('latin1') != urlsplit(expected).netloc:
            status = 403
        elif b'origin' in headers and headers[b'origin'].decode('latin1') != expected:
            status = 403
        if status:
            await send({'type': 'http.response.start', 'status': status,
                        'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
            await send({'type': 'http.response.body', 'body': b'{"detail":"Open Deck from its desktop app."}'})
            return
        await self.app(scope, receive, send)


class PrivateAPIResponses:
    """Prevent HTTP caches from retaining research, personal records or errors."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/'):
            return await self.app(scope, receive, send)

        async def private_send(message):
            if message['type'] == 'http.response.start':
                headers = [(key, value) for key, value in message.get('headers', [])
                           if key.lower() not in {b'cache-control', b'x-content-type-options'}]
                message = {**message, 'headers': headers + [
                    (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')]}
            await send(message)

        await self.app(scope, receive, private_send)
