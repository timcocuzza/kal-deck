"""Build when needed and start one foreground, loopback-only app service."""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8000"


def build_signature(root: Path) -> str:
    paths = [root / name for name in ("index.html", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts")]
    for directory in ("src", "public"):
        paths.extend(path for path in (root / directory).rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def existing_service() -> bool:
    """Return False for a free port; refuse to reuse an unrelated/unhealthy app."""
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=2):
            pass
    except ConnectionRefusedError:
        return False
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"{URL}/api/health", timeout=3) as response:
            health = json.load(response)
        with opener.open(f"{URL}/openapi.json", timeout=3) as response:
            schema = json.load(response)
        if health.get("status") == "ok" and health.get("database") == "ok" and schema.get("info", {}).get("title") == "Deck":
            return True
    except (OSError, ValueError, AttributeError):
        pass
    raise RuntimeError("Port 8000 is occupied, but a healthy Deck service could not be confirmed. Stop that service before retrying; no process was stopped automatically.")


def main() -> int:
    os.chdir(ROOT)
    try:
        if existing_service():
            print(f"Deck is already running: {URL}\nKeep its original terminal open. To apply code changes, stop it there with Ctrl+C and run this command again.", flush=True)
            return 0
        signature = build_signature(ROOT)
        marker = ROOT / "dist" / ".build-signature"
        if not (ROOT / "dist" / "index.html").is_file() or not marker.is_file() or marker.read_text().strip() != signature:
            if not (ROOT / "node_modules").is_dir():
                raise RuntimeError("Browser dependencies missing. Run npm ci first.")
            subprocess.run(["npm", "run", "build"], check=True)
            marker.write_text(signature + "\n")
        else:
            print("Interface is up to date; skipping build.", flush=True)
        print(f"Starting Deck at {URL}\nKeep this terminal open while using the app. Press Ctrl+C to stop.\nTo install the app, open Data in Chrome or Edge.", flush=True)
        os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"])
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Could not start Deck: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
