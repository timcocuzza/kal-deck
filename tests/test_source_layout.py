"""Cross-platform regressions that Linux's normal filesystem would conceal."""
from collections import defaultdict
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourceLayoutTests(unittest.TestCase):
    def test_typescript_modules_have_unambiguous_case_insensitive_names(self):
        names = defaultdict(list)
        for path in (ROOT / 'src').rglob('*'):
            if path.suffix in ('.ts', '.tsx'):
                # TS resolves .ts before .tsx, even when the import's case matches
                # the .tsx component on a case-insensitive Mac/Windows volume.
                names[str(path.relative_to(ROOT).with_suffix('')).casefold()].append(str(path.relative_to(ROOT)))
        collisions = [paths for paths in names.values() if len(paths) > 1]
        self.assertEqual(collisions, [], f'Ambiguous TypeScript imports: {collisions}')

    def test_windows_line_ending_defaults_leave_checkout_clean_in_isolated_git(self):
        with tempfile.TemporaryDirectory(prefix='deck-crlf-') as temporary:
            root = Path(temporary)
            source, checkout = root / 'source', root / 'checkout'
            source.mkdir()
            config = root / 'gitconfig'
            config.write_text('[core]\n\tautocrlf = true\n', encoding='utf-8')
            env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
            env.update(GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1')

            def git(*arguments, environment=env):
                return subprocess.check_output(['git', *map(str, arguments)], env=environment,
                                               stderr=subprocess.DEVNULL, text=True)

            git('-C', source, 'init', '-b', 'main')
            (source / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
            (source / 'fixture.txt').write_bytes(b'one\ntwo\n')
            git('-C', source, 'add', '.')
            git('-C', source, '-c', 'user.name=Deck Test', '-c', 'user.email=test@example.invalid',
                'commit', '-m', 'Line ending fixture')
            git('clone', source, checkout)
            self.assertEqual((checkout / 'fixture.txt').read_bytes(), b'one\ntwo\n')
            isolated = dict(env, GIT_CONFIG_GLOBAL=os.devnull)
            self.assertEqual(git('-C', checkout, 'status', '--porcelain', environment=isolated), '')
