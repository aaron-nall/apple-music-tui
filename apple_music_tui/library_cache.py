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
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_name TEXT NOT NULL,
    track_name TEXT NOT NULL,
    track_position INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_playlists_name ON playlists(playlist_name);
CREATE TABLE IF NOT EXISTS cache_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lyrics (
    track_name TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    synced_lyrics TEXT,
    plain_lyrics TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (track_name, artist, album)
);
"""


class LibraryCache:
    """Read/write cache for library album and track metadata."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        try:
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
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

    def get_album_tracks(self, album_name: str, artist: str = "") -> list[str]:
        if artist:
            rows = self._conn.execute(
                "SELECT track_name FROM tracks WHERE album = ? AND artist = ? ORDER BY track_number",
                (album_name, artist),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT track_name FROM tracks WHERE album = ? ORDER BY track_number",
                (album_name,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_playlists(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT playlist_name FROM playlists ORDER BY playlist_name COLLATE NOCASE"
        ).fetchall()
        return [r[0] for r in rows]

    def get_playlist_tracks(self, playlist_name: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT track_name FROM playlists WHERE playlist_name = ? ORDER BY track_position",
            (playlist_name,),
        ).fetchall()
        return [r[0] for r in rows]

    def replace_playlists(self, playlists: dict[str, list[str]]) -> None:
        """Replace all cached playlists with a fresh set."""
        with self._conn:
            self._conn.execute("DELETE FROM playlists")
            rows = []
            for name, tracks in playlists.items():
                for pos, track in enumerate(tracks, start=1):
                    rows.append((name, track, pos))
            self._conn.executemany(
                "INSERT INTO playlists (playlist_name, track_name, track_position) VALUES (?, ?, ?)",
                rows,
            )

    def has_playlists(self) -> bool:
        row = self._conn.execute("SELECT COUNT(*) FROM playlists").fetchone()
        return row[0] > 0

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

    def get_lyrics(self, track: str, artist: str, album: str) -> dict | None:
        """Return cached lyrics or None if not cached."""
        row = self._conn.execute(
            "SELECT synced_lyrics, plain_lyrics FROM lyrics WHERE track_name = ? AND artist = ? AND album = ?",
            (track, artist, album),
        ).fetchone()
        if row is None:
            return None
        return {"synced_lyrics": row[0] or None, "plain_lyrics": row[1] or None}

    def store_lyrics(
        self, track: str, artist: str, album: str, synced: str | None, plain: str | None
    ) -> None:
        """Cache lyrics for a track (upsert)."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO lyrics (track_name, artist, album, synced_lyrics, plain_lyrics, fetched_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (track, artist, album, synced or "", plain or "", datetime.now(timezone.utc).isoformat()),
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
