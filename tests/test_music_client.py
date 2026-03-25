"""Tests for MusicClient state parsing and playlist methods."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apple_music_tui.music_client import MusicClient


def _make_state_output(
    state: str = "playing",
    track: str = "Test Song",
    artist: str = "Test Artist",
    album: str = "Test Album",
    position: str = "42.5",
    duration: str = "180.0",
    volume: str = "75",
    shuffle: str = "on",
    repeat: str = "all",
    playlist: str = "My Playlist",
) -> str:
    return (
        f"STATE: {state}\n"
        f"TRACK: {track}\n"
        f"ARTIST: {artist}\n"
        f"ALBUM: {album}\n"
        f"POSITION: {position}\n"
        f"DURATION: {duration}\n"
        f"VOLUME: {volume}\n"
        f"SHUFFLE: {shuffle}\n"
        f"REPEAT: {repeat}\n"
        f"PLAYLIST: {playlist}"
    )


@pytest.fixture
def client() -> MusicClient:
    return MusicClient()


class TestGetStateDefaults:
    async def test_returns_defaults_when_run_returns_none(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        state = await client.get_state()
        assert state["running"] is False
        assert state["state"] == "stopped"
        assert state["track"] == ""
        assert state["position"] == 0.0
        assert state["duration"] == 0.0
        assert state["volume"] == 50
        assert state["shuffle"] is False
        assert state["repeat"] == "off"
        assert state["current_playlist"] == ""

    async def test_returns_defaults_when_run_returns_empty_string(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="")
        state = await client.get_state()
        assert state["running"] is False
        assert state["state"] == "stopped"

    async def test_missing_fields_fall_back_to_defaults(self, client: MusicClient) -> None:
        """Partial output (a subset of fields) should not crash; missing fields use defaults."""
        client._run = AsyncMock(return_value="STATE: playing\nTRACK: Partial Song")
        state = await client.get_state()
        assert state["state"] == "playing"
        assert state["track"] == "Partial Song"
        assert state["volume"] == 50       # default
        assert state["shuffle"] is False   # default
        assert state["repeat"] == "off"    # default


class TestGetStatePlayingFields:
    async def test_full_playing_state(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output())
        state = await client.get_state()
        assert state["running"] is True
        assert state["state"] == "playing"
        assert state["track"] == "Test Song"
        assert state["artist"] == "Test Artist"
        assert state["album"] == "Test Album"
        assert state["position"] == 42.5
        assert state["duration"] == 180.0
        assert state["volume"] == 75
        assert state["shuffle"] is True
        assert state["repeat"] == "all"
        assert state["current_playlist"] == "My Playlist"

    async def test_paused_state(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(state="paused", shuffle="off", repeat="off"))
        state = await client.get_state()
        assert state["state"] == "paused"
        assert state["shuffle"] is False
        assert state["repeat"] == "off"

    async def test_stopped_state(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(state="stopped"))
        state = await client.get_state()
        assert state["state"] == "stopped"

    async def test_applescript_state_string_with_extra_words(self, client: MusicClient) -> None:
        """AppleScript may return 'playing' as part of a longer string."""
        client._run = AsyncMock(return_value=_make_state_output(state="playing now"))
        state = await client.get_state()
        assert state["state"] == "playing"


class TestGetStateRepeatMode:
    async def test_repeat_one(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(repeat="one"))
        state = await client.get_state()
        assert state["repeat"] == "one"

    async def test_repeat_all(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(repeat="all"))
        state = await client.get_state()
        assert state["repeat"] == "all"

    async def test_repeat_off(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(repeat="off"))
        state = await client.get_state()
        assert state["repeat"] == "off"

    async def test_repeat_unknown_defaults_to_off(self, client: MusicClient) -> None:
        """Any value not in {one, all, off} should map to 'off' without raising."""
        client._run = AsyncMock(return_value=_make_state_output(repeat="unexpected_value"))
        state = await client.get_state()
        assert state["repeat"] == "off"


class TestGetStateNumberParsing:
    async def test_comma_decimal_separator(self, client: MusicClient) -> None:
        """Some locales use a comma as the decimal separator (e.g. '42,5')."""
        client._run = AsyncMock(
            return_value=_make_state_output(position="42,5", duration="180,0")
        )
        state = await client.get_state()
        assert state["position"] == 42.5
        assert state["duration"] == 180.0

    async def test_integer_volume(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(volume="100"))
        state = await client.get_state()
        assert state["volume"] == 100

    async def test_malformed_position_defaults_to_zero(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(position="not-a-number"))
        state = await client.get_state()
        assert state["position"] == 0.0

    async def test_malformed_volume_defaults_to_zero(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=_make_state_output(volume="bad"))
        state = await client.get_state()
        assert state["volume"] == 0


class TestGetStateEdgeCases:
    async def test_track_name_containing_colon_sequence(self, client: MusicClient) -> None:
        """Track names like 'Act 1: The Beginning' must not be split on the inner ': '."""
        client._run = AsyncMock(
            return_value=_make_state_output(track="Act 1: The Beginning")
        )
        state = await client.get_state()
        assert state["track"] == "Act 1: The Beginning"

    async def test_empty_track_fields(self, client: MusicClient) -> None:
        """Empty string values (nothing playing) should be preserved."""
        client._run = AsyncMock(
            return_value=_make_state_output(track="", artist="", album="", playlist="")
        )
        state = await client.get_state()
        assert state["track"] == ""
        assert state["artist"] == ""
        assert state["album"] == ""
        assert state["current_playlist"] == ""

    async def test_extra_unknown_fields_are_ignored(self, client: MusicClient) -> None:
        """Future AppleScript fields not yet known to Python must not break parsing."""
        output = _make_state_output() + "\nNEWFIELD: some future value"
        client._run = AsyncMock(return_value=output)
        state = await client.get_state()
        assert state["track"] == "Test Song"  # known fields still parse correctly


class TestGetPlaylists:
    async def test_returns_list_of_names(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="Playlist 1|||Playlist 2|||Playlist 3|||")
        playlists = await client.get_playlists()
        assert playlists == ["Playlist 1", "Playlist 2", "Playlist 3"]

    async def test_returns_empty_list_on_none(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        assert await client.get_playlists() == []

    async def test_returns_empty_list_on_empty_string(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="")
        assert await client.get_playlists() == []

    async def test_strips_whitespace_from_names(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=" Chill |||  Jazz  |||")
        playlists = await client.get_playlists()
        assert playlists == ["Chill", "Jazz"]


class TestGetPlaylistTracks:
    async def test_returns_track_names(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="Track A|||Track B|||Track C|||")
        tracks = await client.get_playlist_tracks("My Playlist")
        assert tracks == ["Track A", "Track B", "Track C"]

    async def test_returns_empty_on_none(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        assert await client.get_playlist_tracks("My Playlist") == []

    async def test_returns_empty_on_empty_string(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="")
        assert await client.get_playlist_tracks("My Playlist") == []

    async def test_single_track(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="Only Track|||")
        tracks = await client.get_playlist_tracks("Solo")
        assert tracks == ["Only Track"]


class TestGetAlbums:
    async def test_returns_deduplicated_sorted_albums(self, client: MusicClient) -> None:
        raw = "Zulu Album|||Alpha Album|||Zulu Album|||>>>Artist Z|||Artist A|||Artist Z|||"
        client._run = AsyncMock(return_value=raw)
        albums = await client.get_albums()
        assert albums == [("Alpha Album", "Artist A"), ("Zulu Album", "Artist Z")]

    async def test_returns_empty_on_none(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        assert await client.get_albums() == []

    async def test_returns_empty_on_empty_string(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="")
        assert await client.get_albums() == []

    async def test_skips_empty_album_names(self, client: MusicClient) -> None:
        raw = "Album A||||||>>>Artist A||||||"
        client._run = AsyncMock(return_value=raw)
        albums = await client.get_albums()
        assert albums == [("Album A", "Artist A")]

    async def test_handles_missing_separator(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="no separator here")
        assert await client.get_albums() == []


class TestGetAlbumTracks:
    async def test_returns_track_names(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="Song 1|||Song 2|||Song 3|||")
        tracks = await client.get_album_tracks("My Album")
        assert tracks == ["Song 1", "Song 2", "Song 3"]

    async def test_returns_empty_on_none(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        assert await client.get_album_tracks("My Album") == []

    async def test_escapes_album_name(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value="Track|||")
        await client.get_album_tracks('Album "With" Quotes')
        script = client._run.call_args[0][0]
        assert 'Album \\"With\\" Quotes' in script


class TestPlayAlbum:
    async def test_escapes_album_name(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        await client.play_album('Album "Test"')
        script = client._run.call_args[0][0]
        assert 'Album \\"Test\\"' in script


class TestPlayAlbumTrack:
    async def test_plays_correct_track_directly(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        await client.play_album_track("My Album", 3)
        script = client._run.call_args[0][0]
        assert "item 3 of albumTracks" in script
        assert '"My Album"' in script

    async def test_escapes_album_name(self, client: MusicClient) -> None:
        client._run = AsyncMock(return_value=None)
        await client.play_album_track('Album "Test"', 1)
        script = client._run.call_args[0][0]
        assert 'Album \\"Test\\"' in script
