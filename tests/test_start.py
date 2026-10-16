"""Startup checks use disposable files and mocked sockets, never the saved DB."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location("deck_start", Path(__file__).resolve().parents[1] / "scripts/start.py")
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


class StartTests(unittest.TestCase):
    def test_build_signature_tracks_edits_deletions_and_names_not_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("index.html", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts"):
                (root / name).write_text(name)
            (root / "src").mkdir()
            (root / "public").mkdir()
            source = root / "src/main.tsx"
            source.write_text("original")
            initial = startup.build_signature(root)
            (root / "test.sqlite3").write_text("saved bets")
            self.assertEqual(initial, startup.build_signature(root))
            source.write_text("changed")
            self.assertNotEqual(initial, startup.build_signature(root))
            source.write_text("original")
            source.rename(root / "src/renamed.tsx")
            self.assertNotEqual(initial, startup.build_signature(root))
            (root / "src/renamed.tsx").unlink()
            self.assertNotEqual(initial, startup.build_signature(root))

    @patch.object(startup.socket, "create_connection", side_effect=ConnectionRefusedError)
    def test_free_port_starts_normally(self, connect):
        self.assertFalse(startup.existing_service())

    @patch.object(startup, "build_opener")
    @patch.object(startup.socket, "create_connection")
    def test_healthy_app_can_be_reused(self, connect, opener):
        connect.return_value.__enter__ = Mock()
        connect.return_value.__exit__ = Mock()
        opener.return_value.open.side_effect = [io.BytesIO(b'{"status":"ok","database":"ok"}'), io.BytesIO(b'{"info":{"title":"Kalshi Deck"}}')]
        self.assertTrue(startup.existing_service())

    @patch.object(startup, "build_opener")
    @patch.object(startup.socket, "create_connection")
    def test_other_or_unhealthy_service_is_not_reused(self, connect, opener):
        connect.return_value.__enter__ = Mock()
        connect.return_value.__exit__ = Mock()
        for response in (b'{"info":{"title":"Other app"}}', b'not json'):
            opener.return_value.open.side_effect = [io.BytesIO(b'{"status":"ok","database":"ok"}'), io.BytesIO(response)]
            with self.assertRaisesRegex(RuntimeError, "Port 8000 is occupied"):
                startup.existing_service()


if __name__ == "__main__":
    unittest.main()
