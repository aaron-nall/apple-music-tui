"""Tests for LibraryCache."""
from __future__ import annotations

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
