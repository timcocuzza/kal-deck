"""One-time desktop setup. Afterwards launch and update Deck from its app icon."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

from manage_desktop import Manager, REMOTE, atomic_json, clean_environment, emit, installation_lock, run

ROOT = Path(__file__).resolve().parents[1]


def default_home():
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'DeckRuntime'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/DeckRuntime'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'deck-source'


def detect_tools():
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError('Install Python 3.14 and run this setup with that Python.')
    node, npm, git = (shutil.which(name) for name in ('node', 'npm', 'git'))
    if not all((node, npm, git)):
        raise RuntimeError('Install Git, Node.js 24, and Python 3.14 first, then reopen your terminal.')
    version = subprocess.check_output([node, '--version'], text=True).strip()
    if not version.startswith(('v24.', 'v26.')):
        raise RuntimeError('Deck setup requires Node.js 24 LTS or Node.js 26.')
    npm_path = Path(npm).resolve()
    if npm_path.suffix.lower() in ('.cmd', '.exe'):
        npm_path = Path(node).parent / 'node_modules/npm/bin/npm-cli.js'
    if not npm_path.is_file() or npm_path.name != 'npm-cli.js':
        raise RuntimeError('Could not locate npm-cli.js. Install the standard Node.js 24 distribution.')
    return {'python': str(Path(sys._base_executable).resolve()), 'node': str(Path(node).resolve()),
            'npm_cli': str(npm_path), 'git': str(Path(git).resolve())}


def desktop_quote(value):
    # Desktop Entry Exec escaping has a separate grammar from shell escaping.
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def shortcuts(home, tools, root=ROOT):
    launcher = home / 'launch.py'
    python = tools['python']
    icons = home / 'icons'
    icons.mkdir(exist_ok=True)
    for extension in ('png', 'ico', 'icns'):
        shutil.copy2(root / f'desktop/icons/deck.{extension}', icons / f'deck.{extension}')
    if sys.platform == 'darwin':
        app = Path.home() / 'Applications/Deck.app'
        marker = app / 'Contents/deck-source-launcher'
        if app.exists() and not marker.exists():
            raise RuntimeError('~/Applications/Deck.app already exists. Move that old app aside, then rerun setup; your data is safe.')
        contents = app / 'Contents'
        (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
        (contents / 'Resources').mkdir(exist_ok=True)
        shutil.copy2(icons / 'deck.icns', contents / 'Resources/deck.icns')
        with (contents / 'Info.plist').open('wb') as handle:
            plistlib.dump({'CFBundleName': 'Deck', 'CFBundleDisplayName': 'Deck', 'CFBundleIdentifier': 'com.getwellsedge.deck.launcher',
                          'CFBundleExecutable': 'Deck', 'CFBundleIconFile': 'deck.icns', 'CFBundlePackageType': 'APPL',
                          'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0', 'LSUIElement': True}, handle)
        executable = contents / 'MacOS/Deck'
        executable.write_text('#!/bin/sh\nexec ' + shlex.quote(python) + ' ' + shlex.quote(str(launcher)) + '\n', encoding='utf-8')
        executable.chmod(0o755)
        marker.write_text('Deck source launcher\n', encoding='utf-8')
        print(f'Open {app} to launch Deck. You can drag it to the Dock.')
    elif os.name == 'nt':
        pythonw = str(Path(python).with_name('pythonw.exe'))
        if not Path(pythonw).exists():
            raise RuntimeError('pythonw.exe is missing. Install Python with its Windows GUI launcher.')
        env = dict(os.environ, DECK_LINK_PYTHON=pythonw, DECK_LINK_LAUNCHER=str(launcher), DECK_LINK_ICON=str(icons / 'deck.ico'))
        script = '''$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
  $link = $shell.CreateShortcut((Join-Path $folder 'Deck.lnk'))
  $link.TargetPath = $env:DECK_LINK_PYTHON
  $link.Arguments = '"' + $env:DECK_LINK_LAUNCHER + '"'
  $link.IconLocation = $env:DECK_LINK_ICON
  $link.WorkingDirectory = Split-Path $env:DECK_LINK_LAUNCHER
  $link.Save()
}'''
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], env=env, check=True)
        print('Deck shortcuts are ready on the desktop and in Start.')
    else:
        applications = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications'
        applications.mkdir(parents=True, exist_ok=True)
        entry = applications / 'com.getwellsedge.deck.desktop'
        if entry.exists():
            shutil.copy2(entry, home / 'previous-launcher.desktop')
        entry.write_text('[Desktop Entry]\nType=Application\nName=Deck\nComment=Your personal NFL research workspace\n'
                         f'Exec={desktop_quote(python)} {desktop_quote(launcher)}\nIcon={icons / "deck.png"}\n'
                         'Terminal=false\nCategories=Office;\nStartupWMClass=Deck\n', encoding='utf-8')
        entry.chmod(0o644)
        if shutil.which('update-desktop-database'):
            subprocess.run(['update-desktop-database', str(applications)], check=True)
        print('Deck is ready in your app launcher.')


def install(home, tools, source=ROOT, create_shortcuts=True):
    home = home.resolve()
    os.umask(0o077)
    with installation_lock(home), (home / 'setup.log').open('wb') as log:
        if (home / 'state.json').exists():
            # Repair only the shortcut/bootstrap; never replace existing code or data.
            current_tools = json.loads((home / 'tools.json').read_text(encoding='utf-8'))
            if current_tools != tools:
                raise RuntimeError('The installed tool paths changed. Preserve DeckRuntime and repair its tools.json before updating.')
            Manager(home, log).verify_release(json.loads((home / 'state.json').read_text())['current'])
        else:
            emit('preparing', 'Setting up your own Deck installation…')
            git = tools['git']
            if run([git, '-C', source, 'status', '--porcelain'], cwd=source, log=log, capture=True):
                raise RuntimeError('The setup checkout has uncommitted changes. Use a clean, committed checkout.')
            revision = run([git, '-C', source, 'rev-parse', 'HEAD^{commit}'], cwd=source, log=log, capture=True)
            atomic_json(home / 'tools.json', tools)
            repository = home / 'repository.git'
            if not repository.exists():
                run([git, '-c', f'core.hooksPath={home / "no-hooks"}', 'clone', '--bare', '--no-hardlinks', source, repository],
                    cwd=home, log=log)
            manager = Manager(home, log)
            # A retry can start from a newer local checkout after an interrupted setup.
            manager.git('fetch', '--no-tags', str(source), revision)
            manager.git('remote', 'set-url', 'origin', REMOTE)
            manager.build(revision)
            atomic_json(home / 'state.json', {'current': revision, 'previous': None})
        shutil.copy2(source / 'desktop/launch.py', home / 'launch.py')
        if create_shortcuts:
            shortcuts(home, tools, source)
    print(f'Deck setup complete. Runtime: {home}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=default_home(), help='Advanced: use a separate runtime directory.')
    parser.add_argument('--no-shortcuts', action='store_true', help='For CI validation without changing the desktop.')
    args = parser.parse_args()
    try:
        install(args.home, detect_tools(), create_shortcuts=not args.no_shortcuts)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Setup could not finish: {error}\nDetails: {args.home / "setup.log"}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
