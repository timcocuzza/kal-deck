"""Exercise the actual private backend, restart, and upgrade backup in temp data."""
import argparse
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--executable', type=Path)
args = parser.parse_args()
command = [str(args.executable.resolve())] if args.executable else [sys.executable, str(root / 'desktop/backend_entry.py')]
opener = build_opener(ProxyHandler({}))

with tempfile.TemporaryDirectory(prefix='deck-smoke-') as temporary:
    database = Path(temporary) / 'data/deck.sqlite3'
    for iteration, version in enumerate(('0.1.0', '0.1.1')):
        token = secrets.token_hex(32)
        environment = {k: v for k, v in os.environ.items() if not k.startswith('DECK_')}
        environment.update(DECK_DESKTOP_TOKEN=token, DECK_DATABASE_PATH=str(database), DECK_DESKTOP_VERSION=version,
                           PYTHONTZPATH='')  # Exercise bundled timezone data, even on Unix.
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, env=environment, cwd=root)
            try:
                lines = queue.Queue()
                threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
                startup = json.loads(lines.get(timeout=30))
                assert startup['type'] == 'deck-backend'
                origin = f'http://127.0.0.1:{startup["port"]}'

                def request(path, *, authorized=True, headers=None, body=None, method='GET'):
                    values = {'X-Deck-Desktop-Token': token} if authorized else {}
                    values.update(headers or {})
                    payload = json.dumps(body).encode() if body is not None else None
                    req = Request(origin + path, headers=values, data=payload, method=method)
                    try:
                        with opener.open(req, timeout=3) as response:
                            return response.status, response.read(), dict(response.headers)
                    except HTTPError as error:
                        return error.code, error.read(), dict(error.headers)

                for attempt in range(100):
                    try:
                        if request('/api/health')[0] == 200:
                            break
                    except (OSError, URLError):
                        pass
                    if process.poll() is not None:
                        raise RuntimeError('Backend exited during startup')
                    time.sleep(.1)
                else:
                    raise RuntimeError('Backend was not ready within ten seconds')
                assert request('/api/tracker', authorized=False)[0] == 401
                assert request('/', authorized=False)[0] == 401
                assert request('/api/health', headers={'Host': 'attacker.example'})[0] == 403
                assert request('/api/watchlist', headers={'Origin': 'https://attacker.example'})[0] == 403
                status, body, headers = request('/api/tracker')
                assert status == 200 and headers['cache-control'] == 'no-store'
                assert b'<title>Deck</title>' in request('/')[1]
                assert request('/openapi.json')[0] == 404
                if iteration == 0:
                    entry = {'ticker': 'KXNFLRECYDS-EXAMPLE-50', 'kind': 'prop', 'season': 2026,
                             'week': 6, 'game_id': '2026_06_SEA_DEN', 'label': 'Smoke fixture'}
                    assert request('/api/watchlist', method='PUT', body=entry,
                                   headers={'Origin': origin, 'Content-Type': 'application/json'})[0] == 200
                else:
                    assert json.loads(request('/api/watchlist')[1])['entries'][0]['label'] == 'Smoke fixture'
                    assert list((database.parent / 'backups').glob('*.sqlite3'))
            except BaseException:
                errors.seek(0)
                sys.stderr.write(errors.read(12000).decode(errors='replace'))
                raise
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError('Backend did not exit when its desktop owner closed stdin')
                process.stdout.close()
            assert process.returncode == 0, f'Backend exit code: {process.returncode}'
print('Desktop backend: access boundary, assets, persistent data, upgrade backup, and clean shutdown passed.')
