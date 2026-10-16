"""Version backups for local desktop upgrades, kept outside application files."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4


def prepare_data(path: Path, version: str):
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('Invalid desktop version')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = path.parent / 'app-version.json'
    previous = None
    if marker.exists():
        try:
            previous = json.loads(marker.read_text()).get('version')
        except (ValueError, AttributeError):
            pass
    if previous == version:
        return
    if path.exists():
        backups = path.parent / 'backups'
        backups.mkdir(exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        target = backups / f'before-{version}-{stamp}-{uuid4().hex[:8]}.sqlite3'
        try:
            with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(target)) as destination:
                    source.backup(destination)
                    if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('The pre-update backup failed its integrity check.')
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': version}) + '\n')
    temporary.replace(marker)
