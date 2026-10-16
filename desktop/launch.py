"""Stable per-user launcher; copied outside replaceable releases during setup."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def launch(home):
    state = json.loads((home / 'state.json').read_text(encoding='utf-8'))
    revision = state['current']
    if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision):
        raise RuntimeError('Deck’s installed revision is invalid. Run setup again.')
    release = home / 'releases' / revision
    if release.is_symlink() or release.resolve().parent != (home / 'releases').resolve():
        raise RuntimeError('Deck’s release directory is invalid.')
    if json.loads((release / '.deck-ready.json').read_text(encoding='utf-8')) != {'revision': revision, 'protocol': 1}:
        raise RuntimeError('Deck’s installed version has not completed its checks.')
    suffix = 'electron.exe' if os.name == 'nt' else 'Electron.app/Contents/MacOS/Electron' if sys.platform == 'darwin' else 'electron'
    executable = release / 'node_modules/electron/dist' / suffix
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DECK_', 'PYTHON'))
           and k not in ('ELECTRON_RUN_AS_NODE', 'NODE_OPTIONS')}
    env.update(DECK_SOURCE_HOME=str(home), DECK_SOURCE_REVISION=revision)
    with (home / 'launch.log').open('wb') as log:
        subprocess.Popen([str(executable), str(release)], cwd=release, env=env, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log,
                         **({'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name == 'nt' else {'start_new_session': True}))


def main():
    home = Path(__file__).resolve().parent
    try:
        launch(home)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        message = f'Deck could not open: {error}\nYour personal data has not been removed. Run the Deck setup again to repair the launcher.'
        (home / 'launch-error.txt').write_text(message, encoding='utf-8')
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'Deck', 0x10)
        elif sys.platform == 'darwin':
            subprocess.run(['osascript', '-e', 'on run argv\ndisplay dialog (item 1 of argv) with title "Deck" buttons {"OK"} default button "OK"\nend run', message], check=False)
        else:
            subprocess.run(['notify-send', 'Deck could not open', message], check=False)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
