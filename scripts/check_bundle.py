"""Keep the built JS/CSS transfer budget visible; run after npm run build."""
import gzip
from pathlib import Path

assets = Path('dist/assets')
for extension, budget in [('js', 120_000), ('css', 12_000)]:
    files = list(assets.glob(f'*.{extension}'))
    if not files:
        raise SystemExit(f'No built {extension} files found')
    size = sum(len(gzip.compress(path.read_bytes())) for path in files)
    print(f'{extension}: {size:,} gzip bytes / {budget:,} budget')
    if size > budget:
        raise SystemExit('Bundle budget exceeded; review the performance impact before changing the budget.')
