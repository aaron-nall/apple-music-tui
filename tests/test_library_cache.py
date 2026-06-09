"""Tests for LibraryCache."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from apple_music_tui.library_cache import LibraryCache


@pytest.fixture
def cache(tmp_path: Path) -> LibraryCache:
    return LibraryCache(db_path=tmp_path / "test.db")


def _sample_tracks() -> list[dict]:
    return [
        {"track_name": "Song A", "album": "Zulu Album", "artist": "Artist Z", "track_number": 1},
        {"track_name": "Song B", "album": "Zulu Album", "artist": "Artist Z", "track_number": 2},
        {"track_name": "Song C", "album": "Alpha Album", "artist": "Artist A", "track_number": 1},
    ]


class TestIsEmpty:
    def test_empty_on_init(self, cache: LibraryCache) -> None:
        assert cache.is_empty() is True

    def test_not_empty_after_replace(self, cache: LibraryCache) -> None:
        cache.replace_all(_sample_tracks())
        assert cache.is_empty() is False


class TestGetAlbums:
    def test_returns_distinct_sorted_albums(self, cache: LibraryCache) -> None:
        cache.replace_all(_sample_tracks())
        albums = cache.get_albums()
        assert albums == [("Alpha Album", "Artist A"), ("Zulu Album", "Artist Z")]

    def test_returns_empty_when_no_data(self, cache: LibraryCache) -> None:
        assert cache.get_albums() == []


class TestGetAlbumTracks:
    def test_returns_tracks_in_order(self, cache: LibraryCache) -> None:
        cache.replace_all(_sample_tracks())
        tracks = cache.get_album_tracks("Zulu Album")
        assert tracks == ["Song A", "Song B"]

    def test_returns_empty_for_unknown_album(self, cache: LibraryCache) -> None:
        cache.replace_all(_sample_tracks())
        assert cache.get_album_tracks("No Such Album") == []


class TestReplaceAll:
    def test_replaces_previous_data(self, cache: LibraryCache) -> None:
        cache.replace_all(_sample_tracks())
        assert len(cache.get_albums()) == 2

        cache.replace_all([
            {"track_name": "New Song", "album": "New Album", "artist": "New Artist", "track_number": 1},
        ])
        albums = cache.get_albums()
        assert albums == [("New Album", "New Artist")]

    def test_sets_last_sync(self, cache: LibraryCache) -> None:
        assert cache.get_last_sync() is None
        cache.replace_all(_sample_tracks())
        assert cache.get_last_sync() is not None


class TestNaiveTimestamps:
    """Timezone-naive stored timestamps must not raise on TTL comparison."""

    def test_get_lyrics_with_naive_fetched_at(self, cache: LibraryCache) -> None:
        cache.store_lyrics("Song", "Artist", "Album", "[00:01.00] hi", "hi")
        with cache._lock, cache._conn:
            cache._conn.execute(
                "UPDATE lyrics SET fetched_at = ?", (datetime.now().isoformat(),)
            )
        result = cache.get_lyrics("Song", "Artist", "Album")
        assert result == {"synced_lyrics": "[00:01.00] hi", "plain_lyrics": "hi"}

    def test_get_last_sync_with_naive_timestamp(self, cache: LibraryCache) -> None:
        cache.replace_all(_sample_tracks())
        with cache._lock, cache._conn:
            cache._conn.execute(
                "UPDATE cache_meta SET value = ? WHERE key = 'last_sync'",
                (datetime.now().isoformat(),),
            )
        last = cache.get_last_sync()
        assert last is not None
        assert last.tzinfo is not None


class TestConcurrentAccess:
    def test_threaded_reads_and_writes(self, cache: LibraryCache) -> None:
        """Hammer the shared connection from multiple threads; must not raise."""
        def write_tracks(_: int) -> None:
            cache.replace_all(_sample_tracks())

        def write_lyrics(i: int) -> None:
            cache.store_lyrics(f"Song {i}", "Artist", "Album", "synced", "plain")

        def read(_: int) -> None:
            cache.get_albums()
            cache.get_album_tracks("Zulu Album")
            cache.is_empty()

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = []
            for i in range(20):
                futures.append(pool.submit(write_tracks, i))
                futures.append(pool.submit(write_lyrics, i))
                futures.append(pool.submit(read, i))
            for f in futures:
                f.result()  # re-raises any exception from the worker

        assert cache.is_empty() is False
