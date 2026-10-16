"""Private backend owned by one Deck desktop process. Never exposes a LAN port."""

import json
import os
from pathlib import Path
import socket
import sys
import threading


def main():
    token = os.environ.get('DECK_DESKTOP_TOKEN', '')
    data_path = os.environ.get('DECK_DATABASE_PATH', '')
    if len(token) < 64 or not data_path or not Path(data_path).is_absolute():
        raise SystemExit('Deck desktop requires a private session and an absolute data path.')
    os.umask(0o077)
    # In a PyInstaller bundle, __file__ and backend.app share the bundle root.
    # In development, Python starts at desktop/, so add the project root.
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.desktop_storage import prepare_data
    prepare_data(Path(data_path), os.environ.get('DECK_DESKTOP_VERSION', '0.1.0'))
    # Windows has no system IANA database. Fail early if packaging omitted ours.
    from zoneinfo import ZoneInfo
    ZoneInfo('America/New_York')
    import uvicorn
    from backend.app import app

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    os.environ['DECK_DESKTOP_ORIGIN'] = f'http://127.0.0.1:{port}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False,
                                         proxy_headers=False, timeout_graceful_shutdown=8,
                                         limit_concurrency=12))

    # Closing stdin on normal quit or a parent crash shuts down this child.
    # A private pipe avoids a public shutdown route and cross-platform signals.
    def parent_lifetime():
        try:
            sys.stdin.buffer.read()
        finally:
            server.should_exit = True
    threading.Thread(target=parent_lifetime, daemon=True).start()
    print(json.dumps({'type': 'deck-backend', 'port': port}), flush=True)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == '__main__':
    main()
