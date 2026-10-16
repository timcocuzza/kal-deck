"""Latest validated source snapshots; failures never overwrite usable data."""

from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3

from .sources.common import SourceData, utc_now


class SnapshotStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS source_snapshots (
                    source_key TEXT PRIMARY KEY,
                    payload BLOB,
                    metadata TEXT,
                    attempted_at TEXT NOT NULL,
                    error TEXT
                )
            """)

    def save(self, key: str, data: SourceData):
        payload = gzip.compress(json.dumps(data.rows, allow_nan=False, separators=(",", ":")).encode())
        metadata = json.dumps({
            "url": data.url, "fetched_at": data.fetched_at,
            "source_updated_at": data.source_updated_at, "row_count": len(data.rows),
            "context": data.context, "warnings": data.warnings,
        }, allow_nan=False)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                INSERT INTO source_snapshots(source_key, payload, metadata, attempted_at, error)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(source_key) DO UPDATE SET
                    payload=excluded.payload, metadata=excluded.metadata,
                    attempted_at=excluded.attempted_at, error=NULL
            """, (key, payload, metadata, utc_now()))

    def record_failure(self, key: str, error: str):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                INSERT INTO source_snapshots(source_key, attempted_at, error)
                VALUES (?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    attempted_at=excluded.attempted_at, error=excluded.error
            """, (key, utc_now(), error))

    def status(self, key: str) -> dict:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT metadata, attempted_at, error FROM source_snapshots WHERE source_key=?", (key,),
            ).fetchone()
        if row is None:
            return {"status": "not_loaded", "fetched_at": None, "attempted_at": None, "error": None}
        metadata, attempted_at, error = row
        result = json.loads(metadata) if metadata else {"fetched_at": None}
        result.update({
            "status": "refresh_failed" if error else "ready",
            "attempted_at": attempted_at, "error": error,
        })
        return result

    def read(self, key: str) -> SourceData | None:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT payload, metadata FROM source_snapshots WHERE source_key=?", (key,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        metadata = json.loads(row[1])
        return SourceData(
            rows=json.loads(gzip.decompress(row[0])), url=metadata["url"],
            fetched_at=metadata["fetched_at"], source_updated_at=metadata["source_updated_at"],
            context=metadata["context"], warnings=metadata["warnings"],
        )
