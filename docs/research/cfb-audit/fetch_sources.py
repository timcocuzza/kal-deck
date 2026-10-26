"""Download public audit inputs to /tmp only; no account, paid API or app mutation."""
import csv
import gzip
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

CACHE = Path('/tmp/deck-cfb-audit')
SOURCES = {
    'schedule': ('cfb_schedules', 'cfb_schedules_2026.csv.gz'),
    'team_box': ('espn_cfb_team_box', 'team_box_2026.csv'),
    'adv_team': ('espn_cfb_adv_team', 'adv_team_2026.csv'),
    'adv_defensive': ('espn_cfb_adv_defensive', 'adv_defensive_2026.csv'),
    'adv_situational': ('espn_cfb_adv_situational', 'adv_situational_2026.csv'),
}

def get(url, limit=15_000_000):
    with urlopen(Request(url, headers={'User-Agent':'Deck-CFB-feasibility-audit'}), timeout=45) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError('Download exceeded audit limit')
        return body

def read_csv(path):
    body = Path(path).read_bytes()
    if str(path).endswith('.gz'):
        body = gzip.decompress(body)
    return list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))

def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for key, (tag, name) in SOURCES.items():
        meta_url = f'https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/{tag}'
        release = json.loads(get(meta_url))
        asset = next(a for a in release['assets'] if a['name'] == name)
        url = asset['browser_download_url']
        body = get(url)
        path = CACHE / name
        path.write_bytes(body)
        rows = read_csv(path)
        manifest[key] = {'url':url, 'release_url':release['html_url'], 'asset_updated_at':asset['updated_at'],
                         'downloaded_at':datetime.now(timezone.utc).isoformat(), 'bytes':len(body),
                         'sha256':hashlib.sha256(body).hexdigest(), 'path':str(path), 'rows':len(rows),
                         'columns':list(rows[0]) if rows else []}
        print(key, len(rows), list(rows[0]) if rows else [], flush=True)
        print('sample', json.dumps(rows[0])[:4000] if rows else '', flush=True)
    (CACHE/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')

if __name__ == '__main__':
    main()
