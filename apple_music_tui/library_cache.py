"""SQLite cache for Apple Music library metadata."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from apple_music_tui.config import CONFIG_DIR

_log = logging.getLogger(__name__)

DB_PATH = CONFIG_DIR / "library_cache.db"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    track_name TEXT NOT NULL,
    track_number INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album);
CREATE TABLE IF NOT EXISTS cache_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class LibraryCache:
    """Read/write cache for library album and track metadata."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        try:
            self._conn = sqlite3.connect(str(db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error:
            _log.exception("Failed to open library cache")
            raise

    def close(self) -> None:
        self._conn.close()

    def is_empty(self) -> bool:
        row = self._conn.execute("SELECT COUNT(*) FROM tracks").fetchone()
        return row[0] == 0

    def get_albums(self) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT DISTINCT album, artist FROM tracks ORDER BY album COLLATE NOCASE"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def get_album_tracks(self, album_name: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT track_name FROM tracks WHERE album = ? ORDER BY track_number",
            (album_name,),
        ).fetchall()
        return [r[0] for r in rows]

    def replace_all(self, tracks: list[dict]) -> None:
        """Replace all cached tracks with a fresh set."""
        with self._conn:
            self._conn.execute("DELETE FROM tracks")
            self._conn.executemany(
                "INSERT INTO tracks (album, artist, track_name, track_number) VALUES (?, ?, ?, ?)",
                [(t["album"], t["artist"], t["track_name"], t["track_number"]) for t in tracks],
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('last_sync', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

    def get_last_sync(self) -> datetime | None:
        row = self._conn.execute(
            "SELECT value FROM cache_meta WHERE key = 'last_sync'"
        ).fetchone()
        if row:
            try:
                return datetime.fromisoformat(row[0])
            except ValueError:
                return None
        return None
