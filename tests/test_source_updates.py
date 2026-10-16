"""Use real disposable Git repositories; never touch the user's source or data."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deck_manager', Path(__file__).resolve().parents[1] / 'scripts/manage_desktop.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class SourceUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='deck-update-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / 'upstream'
        self.source.mkdir()
        self.git('init', '-b', 'main')
        self.first = self.commit('one')
        self.home = self.base / 'runtime'
        self.home.mkdir()
        subprocess.run(['git', 'clone', '--bare', str(self.source), str(self.home / 'repository.git')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        manager.atomic_json(self.home / 'tools.json', {'git': 'git', 'python': sys.executable, 'node': sys.executable, 'npm_cli': ''})
        manager.atomic_json(self.home / 'state.json', {'current': self.first, 'previous': None})
        self.fake_build(self.first)
        self.log = (self.home / 'update.log').open('wb')
        self.addCleanup(self.log.close)
        self.updater = manager.Manager(self.home, self.log)
        self.remote = patch.object(manager, 'REMOTE', str(self.source))
        self.remote.start()
        self.addCleanup(self.remote.stop)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.source), '-c', 'user.name=Deck Test',
                                        '-c', 'user.email=test@example.invalid', *args], stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, contents):
        (self.source / 'fixture.txt').write_text(contents)
        self.git('add', 'fixture.txt'); self.git('commit', '-m', contents)
        return self.git('rev-parse', 'HEAD')

    def fake_build(self, revision):
        release = manager.release_path(self.home, revision)
        for file in (manager.python_path(release), manager.electron_path(release), release / 'dist/index.html',
                     release / 'desktop/main.cjs', release / 'scripts/manage_desktop.py'):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('fixture')
        manager.atomic_json(release / '.deck-ready.json', {'revision': revision, 'protocol': 1})

    def test_preparation_is_separate_from_atomic_activation(self):
        second = self.commit('two')
        personal = self.base / 'personal.sqlite3'
        personal.write_bytes(b'untouched personal records')
        with patch.object(self.updater, 'build', side_effect=self.fake_build):
            self.updater.prepare()
        self.assertEqual(self.updater.state()['current'], self.first)
        self.assertEqual(manager.read_json(self.home / 'ready.json')['revision'], second)
        self.updater.activate()
        self.assertEqual(self.updater.state(), {'current': second, 'previous': self.first})
        self.assertEqual(personal.read_bytes(), b'untouched personal records')

    def test_build_failure_keeps_the_installed_revision(self):
        self.commit('two')
        with patch.object(self.updater, 'build', side_effect=RuntimeError('Build failed')):
            with self.assertRaises(RuntimeError):
                self.updater.prepare()
        self.assertEqual(self.updater.state()['current'], self.first)
        self.assertFalse((self.home / 'ready.json').exists())

    def test_no_change_does_not_rebuild(self):
        with patch.object(self.updater, 'build') as build:
            self.updater.prepare()
            build.assert_not_called()

    def test_rewritten_history_cannot_downgrade_the_installed_app(self):
        second = self.commit('two')
        with patch.object(self.updater, 'build', side_effect=self.fake_build):
            self.updater.prepare()
        self.updater.activate()
        self.git('reset', '--hard', self.first)
        with self.assertRaises(RuntimeError):
            self.updater.prepare()
        self.assertEqual(self.updater.state()['current'], second)

    def test_unchecked_candidate_cannot_activate(self):
        second = self.commit('two')
        manager.atomic_json(self.home / 'ready.json', {'revision': second, 'from': self.first})
        with self.assertRaises(OSError):
            self.updater.activate()
        self.assertEqual(self.updater.state()['current'], self.first)

    def test_stale_candidate_cannot_replace_a_different_current_version(self):
        second = self.commit('two')
        self.fake_build(second)
        manager.atomic_json(self.home / 'ready.json', {'revision': second, 'from': 'a' * 40})
        with self.assertRaises(RuntimeError):
            self.updater.activate()
        self.assertEqual(self.updater.state()['current'], self.first)

    def test_changed_remote_and_path_traversal_are_rejected(self):
        self.updater.git('remote', 'set-url', 'origin', 'https://attacker.example/repository')
        with self.assertRaises(RuntimeError):
            self.updater.prepare()
        with self.assertRaises(ValueError):
            manager.release_path(self.home, '../personal')

    def test_update_lock_releases_after_an_interrupted_operation(self):
        with self.assertRaises(RuntimeError):
            with manager.installation_lock(self.home):
                raise RuntimeError('failed work')
        with manager.installation_lock(self.home):
            pass
