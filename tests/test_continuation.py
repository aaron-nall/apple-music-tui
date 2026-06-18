"""Tests for the playback-queue continuation state machine in AppleMusicApp.

These cover the unified queue that advances to the next track when one ends:
album queues route to ``play_album_track`` and playlist queues (used when a
user jumps to a track inside a playlist, which Apple Music plays detached with
no native continuation) route to ``play_playlist_track``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apple_music_tui import app as app_mod
from apple_music_tui.config import AppConfig


@pytest.fixture
def music_app(monkeypatch: pytest.MonkeyPatch) -> app_mod.AppleMusicApp:
    """An app instance with a mocked client and no real config/log side effects."""
    monkeypatch.setattr(app_mod, "load_config", lambda: AppConfig.model_construct(theme="textual-dark"))
    app = app_mod.AppleMusicApp()
    app.client = MagicMock()
    app.client.play_playlist_track = AsyncMock()
    app.client.play_album_track = AsyncMock()
    app._alert = lambda msg: None  # bypass the Textual log sink
    return app


async def test_playlist_track_end_advances_via_playlist_track(music_app) -> None:
    # User jumped to track 12 (0-based idx 11); it plays, then ends.
    music_app._set_queue("playlist", "Serj Tankian Essentials", [f"t{i:02d}" for i in range(1, 16)], 11)
    await music_app._handle_continuation({"state": "playing", "track": "t12"})
    await music_app._handle_continuation({"state": "stopped", "track": ""})

    assert music_app._queue_track_idx == 12
    music_app.client.play_playlist_track.assert_awaited_once_with("Serj Tankian Essentials", 13)
    music_app.client.play_album_track.assert_not_awaited()


async def test_album_track_end_advances_via_album_track(music_app) -> None:
    music_app._set_queue("album", "Toxicity", ["a", "b", "c"], 0, artist="System of a Down")
    await music_app._handle_continuation({"state": "playing", "track": "a"})
    await music_app._handle_continuation({"state": "stopped", "track": ""})

    assert music_app._queue_track_idx == 1
    music_app.client.play_album_track.assert_awaited_once_with("Toxicity", 2, "b", "System of a Down")
    music_app.client.play_playlist_track.assert_not_awaited()


async def test_reaching_end_of_queue_clears_kind(music_app) -> None:
    music_app._set_queue("playlist", "P", ["x", "y"], 1)  # already on the last track
    await music_app._handle_continuation({"state": "stopped", "track": ""})

    assert music_app._queue_kind == ""
    music_app.client.play_playlist_track.assert_not_awaited()


async def test_awaiting_play_prevents_double_advance(music_app) -> None:
    # After advancing, a second "stopped" poll within the grace window must not
    # advance again (the new track simply hasn't started playing yet).
    music_app._set_queue("playlist", "P", ["a", "b", "c"], 0)
    await music_app._handle_continuation({"state": "stopped", "track": ""})  # advance to idx 1
    await music_app._handle_continuation({"state": "stopped", "track": ""})  # should be a no-op

    assert music_app._queue_track_idx == 1
    music_app.client.play_playlist_track.assert_awaited_once_with("P", 2)


async def test_playing_resyncs_index_for_duplicate_track_names(music_app) -> None:
    # Duplicate names: hearing the later "dup" must not snap the index backward.
    music_app._set_queue("playlist", "P", ["dup", "mid", "dup", "end"], 0)
    await music_app._handle_continuation({"state": "playing", "track": "dup"})
    assert music_app._queue_track_idx == 0  # first occurrence at/after current idx

    music_app._queue_track_idx = 2
    await music_app._handle_continuation({"state": "playing", "track": "dup"})
    assert music_app._queue_track_idx == 2  # stays on the current matching occurrence
