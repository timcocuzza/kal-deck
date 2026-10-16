"""Build isolated Git revisions and activate only fully checked desktop updates."""
from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

REMOTE = 'https://github.com/timcocuzza/kal-deck.git'
REVISION = re.compile(r'[0-9a-f]{40}')


def emit(status, message, **extra):
    try:
        print(json.dumps({'status': status, 'message': message, **extra}), flush=True)
    except (BrokenPipeError, OSError):
        pass  # Preparing may finish after the user closes the app; never auto-activate.


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def release_path(home, revision):
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError('Invalid installed revision.')
    target = home / 'releases' / revision
    if target.is_symlink() or target.resolve().parent != (home / 'releases').resolve():
        raise ValueError('Invalid release directory.')
    return target


def python_path(release):
    return release / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def electron_path(release):
    suffix = 'electron.exe' if os.name == 'nt' else 'Electron.app/Contents/MacOS/Electron' if sys.platform == 'darwin' else 'electron'
    return release / 'node_modules/electron/dist' / suffix


def clean_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DECK_', 'PYTHON', 'GIT_'))
           and k not in ('ELECTRON_RUN_AS_NODE', 'NODE_OPTIONS')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
               PYTHONUNBUFFERED='1', PYTHONUTF8='1')
    return env


@contextmanager
def installation_lock(home):
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (home / 'update.lock').open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another Deck setup or update is already running.') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def run(command, *, cwd, log, capture=False, timeout=900, env=None):
    environment = clean_environment()
    environment.update(env or {})
    options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    with subprocess.Popen([str(arg) for arg in command], cwd=cwd, env=environment,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else log,
                          stderr=log, **options) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=log, stderr=log, check=False)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RuntimeError('An update step timed out. The installed version is unchanged.') from error
        if process.returncode:
            raise RuntimeError('An update step failed. See the update log; the installed version is unchanged.')
        return output.decode('utf-8').strip() if capture else None


class Manager:
    def __init__(self, home, log):
        self.home = Path(home).resolve()
        self.log = log
        self.tools = read_json(self.home / 'tools.json')
        self.repository = self.home / 'repository.git'
        self.environment = {'PATH': str(Path(self.tools['node']).parent) + os.pathsep + os.environ.get('PATH', '')}

    def git(self, *arguments, capture=False):
        return run([self.tools['git'], '-c', f'core.hooksPath={self.home / "no-hooks"}',
                    '--git-dir', self.repository, *arguments], cwd=self.home, log=self.log,
                   capture=capture, timeout=180, env=self.environment)

    def state(self):
        return read_json(self.home / 'state.json') if (self.home / 'state.json').exists() else {'current': None, 'previous': None}

    def verify_release(self, revision):
        release = release_path(self.home, revision)
        if read_json(release / '.deck-ready.json') != {'revision': revision, 'protocol': 1}:
            raise RuntimeError('The candidate did not complete its checks.')
        for file in (python_path(release), electron_path(release), release / 'dist/index.html',
                     release / 'desktop/main.cjs', release / 'scripts/manage_desktop.py'):
            if not file.is_file():
                raise RuntimeError('The candidate is missing required files.')
        return release

    def build(self, revision):
        release = release_path(self.home, revision)
        if release.exists() and (release / '.deck-ready.json').exists():
            self.verify_release(revision)
            return
        if revision in (self.state()['current'], self.state().get('previous')):
            raise RuntimeError('The installed version needs repair; it will not be overwritten.')
        if release.exists():
            # Only discard our incomplete managed worktree, never a user's checkout.
            self.git('worktree', 'remove', '--force', str(release))
        if shutil.disk_usage(self.home).free < 2 * 1024 ** 3:
            raise RuntimeError('Deck needs at least 2 GB of free disk space to prepare an update.')
        release.parent.mkdir(exist_ok=True)
        self.git('worktree', 'add', '--detach', str(release), revision)
        required = read_json(release / 'package.json').get('deckSourceProtocol')
        if required != 1:
            raise RuntimeError('This version needs a newer Deck setup. Your installed app is unchanged.')
        emit('preparing', 'Installing the update’s components…')
        run([self.tools['python'], '-m', 'venv', release / '.venv'], cwd=release, log=self.log, env=self.environment)
        python = python_path(release)
        run([python, '-m', 'pip', 'install', '--require-hashes', '-r', 'requirements.txt'], cwd=release, log=self.log, env=self.environment)
        run([python, '-m', 'pip', 'check'], cwd=release, log=self.log, env=self.environment)
        npm = [self.tools['node'], self.tools['npm_cli']]
        run([*npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=release, log=self.log, env=self.environment)
        run([self.tools['node'], 'node_modules/electron/install.js'], cwd=release, log=self.log, env=self.environment)
        emit('preparing', 'Building and checking Deck…')
        for file in sorted((release / 'desktop').glob('*.cjs')):
            run([self.tools['node'], '--check', file], cwd=release, log=self.log, env=self.environment)
        for args in ([*npm, 'test'], [*npm, 'run', 'build'],
                     [python, '-m', 'unittest', 'discover', '-s', 'tests'],
                     [python, 'scripts/check_bundle.py'], [python, 'scripts/smoke_desktop.py']):
            run(args, cwd=release, log=self.log, env=self.environment)
        atomic_json(release / '.deck-ready.json', {'revision': revision, 'protocol': 1})
        self.verify_release(revision)

    def cleanup(self):
        state = self.state()
        keep = {state['current'], state.get('previous')}
        if (self.home / 'ready.json').exists():
            keep.add(read_json(self.home / 'ready.json')['revision'])
        for release in (self.home / 'releases').glob('*'):
            if REVISION.fullmatch(release.name) and release.name not in keep:
                release_path(self.home, release.name)  # Reject symlinks before any removal.
                self.git('worktree', 'remove', '--force', str(release))

    def prepare(self):
        if self.git('remote', 'get-url', 'origin', capture=True) != REMOTE:
            raise RuntimeError('The update repository has changed. Re-run the trusted Deck setup.')
        self.cleanup()
        emit('checking', 'Checking for a newer Deck version…')
        # Fetch by an explicit URL. User Git config, hooks, and credential prompts are disabled.
        self.git('fetch', '--no-tags', REMOTE, 'refs/heads/main')
        revision = self.git('rev-parse', 'FETCH_HEAD^{commit}', capture=True)
        current = self.state()['current']
        if revision == current:
            (self.home / 'ready.json').unlink(missing_ok=True)
            emit('idle', 'Deck is up to date.')
            return
        if current:
            self.git('merge-base', '--is-ancestor', current, revision)
        self.build(revision)
        atomic_json(self.home / 'ready.json', {'revision': revision, 'from': current})
        emit('ready', 'Update ready. Save your edits, then restart Deck.', revision=revision[:12])

    def activate(self):
        ready = read_json(self.home / 'ready.json')
        state = self.state()
        if ready['from'] != state['current']:
            raise RuntimeError('The installed version changed while the update was being prepared.')
        self.verify_release(ready['revision'])
        atomic_json(self.home / 'state.json', {'current': ready['revision'], 'previous': state['current']})
        (self.home / 'ready.json').unlink(missing_ok=True)


def process_alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5  # Access denied is not proof of exit.
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'activate'])
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--wait-pid', type=int)
    args = parser.parse_args()
    home = args.home.resolve()
    os.umask(0o077)
    try:
        if args.action == 'activate':
            if not args.wait_pid or args.wait_pid <= 0:
                raise RuntimeError('Restart activation requires the old app process.')
            for _ in range(300):
                if not process_alive(args.wait_pid):
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Deck is still open. The update was not activated.')
        with installation_lock(home), (home / ('update.log' if args.action == 'prepare' else 'restart.log')).open('wb') as log:
            manager = Manager(home, log)
            if args.action == 'prepare':
                manager.prepare()
            else:
                manager.activate()
        if args.action == 'activate':
            subprocess.Popen([manager.tools['python'], str(home / 'launch.py')], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}))
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        emit('error', str(error))
        if args.action == 'activate':
            (home / 'restart-error.txt').write_text(str(error), encoding='utf-8')
            if args.wait_pid and not process_alive(args.wait_pid) and (home / 'launch.py').exists():
                subprocess.Popen([sys.executable, str(home / 'launch.py')], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
