"""Freeze Python + browser assets on each target OS; no runtime Python install."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
if not (root / 'dist/index.html').is_file():
    raise SystemExit('Run npm run build before packaging the desktop backend.')
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
    '--name', 'deck-service', '--distpath', str(root / 'build/desktop/backend'),
    '--workpath', str(root / 'build/desktop/work'), '--specpath', str(root / 'build/desktop'),
    '--paths', str(root), '--add-data', f'{root / "dist"}:dist',
    '--collect-all', 'uvicorn', '--collect-all', 'pydantic',
    '--collect-all', 'tzdata',
    '--collect-submodules', 'backend',
    str(root / 'desktop/backend_entry.py'),
], check=True, cwd=root)
