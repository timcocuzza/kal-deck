import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.desktop_storage import prepare_data


class DesktopStorageTests(unittest.TestCase):
    def test_new_install_is_private_and_upgrade_backup_preserves_all_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile/deck.sqlite3'
            prepare_data(path, '0.1.0')
            self.assertFalse(path.exists(), 'Schema initialization owns database creation')
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('CREATE TABLE personal (notes TEXT)')
                connection.execute('INSERT INTO personal VALUES (?)', ('saved notes',))
            prepare_data(path, '0.1.0')
            self.assertFalse((path.parent / 'backups').exists())
            prepare_data(path, '0.2.0')
            backups = list((path.parent / 'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute('SELECT notes FROM personal').fetchone()[0], 'saved notes')
            prepare_data(path, '0.2.0')
            self.assertEqual(len(list((path.parent / 'backups').glob('*.sqlite3'))), 1)
            self.assertEqual(json.loads((path.parent / 'app-version.json').read_text())['version'], '0.2.0')

    def test_corrupt_database_never_marks_an_upgrade_as_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deck.sqlite3'
            path.write_bytes(b'not sqlite')
            with self.assertRaises(sqlite3.DatabaseError):
                prepare_data(path, '0.2.0')
            self.assertFalse((path.parent / 'app-version.json').exists())
            self.assertEqual(list((path.parent / 'backups').glob('*')), [])

    def test_unsafe_version_cannot_escape_backup_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                prepare_data(Path(directory) / 'deck.sqlite3', '../../elsewhere')
