from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.widgets import Button, Tabs

from apple_music_tui.audio_meter import AudioMeter, AudioMeterError
from apple_music_tui.config import load_config
from apple_music_tui.library_cache import LibraryCache
from apple_music_tui.lyrics import (
    GAP_SENTINEL, TransientLyricsError, fetch_lyrics, find_current_line,
    insert_gap_lines, parse_lrc,
)
from apple_music_tui.music_client import MusicClient, MusicState
from apple_music_tui.themes import CUSTOM_THEMES
from apple_music_tui.widgets.airplay_picker import AirPlayOverlay, AirPlayPicker
from apple_music_tui.widgets.controls import Controls, VolumeBar
from apple_music_tui.widgets.lyrics_overlay import LyricsOverlay
from apple_music_tui.widgets.now_playing import NowPlaying
from apple_music_tui.widgets.playlist_browser import PlaylistBrowser
from apple_music_tui.widgets.status_bar import StatusBar
from apple_music_tui.widgets.visualization_overlay import NUM_VIZ, VisualizationOverlay

_log = logging.getLogger(__name__)


class AppleMusicApp(App):
    """Apple Music TUI controller."""

    TITLE = "Apple Music TUI"

    CSS = """
    Screen {
        background: $surface;
        layers: default overlay;
    }
    #main-container {
        height: auto;
        max-height: 8;
    }
    """

    BINDINGS = [
        Binding("space", "play_pause", "Play/Pause", priority=True),
        Binding("right,l", "next_track", "Next"),
        Binding("left,h", "previous_track", "Previous"),
        Binding("s", "toggle_shuffle", "Shuffle"),
        Binding("r", "cycle_repeat", "Repeat"),
        Binding("t", "cycle_theme", "Theme"),
        Binding("plus,equals_sign", "volume_up", "Vol+"),
        Binding("minus", "volume_down", "Vol-"),
        Binding("a", "toggle_album_sort", "Sort Albums"),
        Binding("o", "toggle_airplay", "AirPlay"),
        Binding("y", "toggle_lyrics", "Lyrics"),
        Binding("v", "cycle_visualization", "Visualizer"),
        Binding("escape", "close_overlay", "Close", show=False, priority=True),
        Binding("tab", "toggle_browse_mode", "Playlists/Albums", priority=True),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "show_help", "Help", priority=True),
    ]

    def __init__(self) -> None:
        self._config = load_config()
        super().__init__()
        self.client = MusicClient()
        # Shared audio meter (RMS for the control bar + FFT for the visualizer).
        # Owned here, started in on_mount, stopped in on_unmount.
        self.audio_meter: AudioMeter | None = None
        self._viz_index: int = -1  # -1 = visualization overlay closed
        self._last_poll: float = 0
        self._last_state: MusicState | None = None
        self._polling: bool = False
        self._last_known_playlist: str = ""  # tracks last auto-expanded playlist
        self._last_known_album: str = ""  # tracks last auto-expanded album
        self._cache: LibraryCache | None = None
        self._syncing: bool = False
        self._t0: float = time.monotonic()
        # Playback queue continuation: advance to the next track when one ends.
        # Apple Music doesn't auto-continue after a single-track album play or
        # `play track N of <playlist>` (which detaches the track into the
        # library), so the poll loop drives advancement for both.
        self._queue_kind: str = ""  # "" (off) | "album" | "playlist"
        self._queue_name: str = ""  # album or playlist name currently playing
        self._queue_artist: str = ""  # album artist (unused for playlists)
        self._queue_track_list: list[str] = []  # ordered track names
        self._queue_track_idx: int = 0  # current index in _queue_track_list
        self._queue_awaiting_play: bool = False  # True after advancing, until "playing" seen
        self._queue_awaiting_since: float = 0.0  # when _queue_awaiting_play was set
        self._queue_play_retries: int = 0  # failed attempts to start the advanced track
        # Lyrics state
        self._lyrics_visible: bool = False
        self._lyrics_track: str = ""
        self._lyrics_artist: str = ""
        self._parsed_lyrics: list[tuple[float, str]] | None = None
        self._lyrics_synced: bool = False
        self._lyrics_current_line: int = -1
        self._lyrics_loading: bool = False
        self._gap_lines: set[int] = set()
        self._gap_end_times: dict[int, float] = {}
        self._last_gap_bold_count: int = -1

    def _alert(self, msg: str) -> None:
        elapsed = time.monotonic() - self._t0
        self.log(f"[{elapsed:.2f}s] {msg}")

    def _start_audio_meter(self) -> None:
        """Start the shared audio meter; degrade gracefully if unavailable."""
        try:
            meter = AudioMeter()
            meter.start()
            self.audio_meter = meter
        except AudioMeterError:
            self.audio_meter = None  # no permission / framework — meters stay flat

    def on_unmount(self) -> None:
        if self.audio_meter is not None:
            try:
                self.audio_meter.stop()
            except Exception:
                pass
            self.audio_meter = None

    def compose(self) -> ComposeResult:
        with Vertical(id="main-container"):
            yield NowPlaying()
            yield Controls()
        yield PlaylistBrowser()
        yield StatusBar()
        yield LyricsOverlay()
        yield VisualizationOverlay()

    def on_mount(self) -> None:
        self._alert("on_mount start")
        # Start the meter off the mount path: SCK setup can block for up to 10s
        # on a cold permission grant. Consumers poll it lazily once it's ready.
        self.run_worker(self._start_audio_meter, thread=True)
        for t in CUSTOM_THEMES:
            self.register_theme(t)
        saved = self._config.theme
        if saved in self.available_themes:
            self.theme = saved
        self.call_later(self._poll_state)
        self._load_library_cached()
        self.call_later(self.screen.set_focus, None)
        self.set_interval(1.0, self._poll_state)
        self.set_interval(0.25, self._interpolate_position)
        self.set_interval(600, self._schedule_sync)
        self._alert("on_mount done")

    async def _poll_state(self) -> None:
        if self._polling:
            return
        self._polling = True
        self._alert("poll_state start")
        try:
            state = await self.client.get_state()
            self._last_state = state
            self._last_poll = time.monotonic()

            np = self.query_one(NowPlaying)
            np.running = state["running"]
            np.track = state["track"]
            np.artist = state["artist"]
            np.album = state["album"]
            np.position = state["position"]
            np.duration = state["duration"]
            np.state = state["state"]

            ctrl = self.query_one(Controls)
            ctrl.playing = state["state"] == "playing"
            ctrl.shuffle = state["shuffle"]
            ctrl.repeat_mode = state["repeat"]
            ctrl.volume = state["volume"]

            browser = self.query_one(PlaylistBrowser)

            # Refresh lyrics if track changed while overlay is open
            if self._lyrics_visible and not self._lyrics_loading:
                if state["track"] != self._lyrics_track or state["artist"] != self._lyrics_artist:
                    self._lyrics_current_line = -1
                    self.run_worker(self._load_lyrics(), group="lyrics")

            if self._queue_kind and self._queue_track_list:
                await self._handle_continuation(state)

            track_index = (self._queue_track_idx + 1) if self._queue_kind else (state.get("track_index") or None)
            browser.set_current_track(state["track"], state.get("album"), track_index)

            # Auto-expand the currently playing playlist or album
            if browser._mode == "playlists":
                current_pl = state["current_playlist"]
                # Only react to playlists we actually list. Jumping to a track
                # detaches it into the "Music" library node (Apple Music reports
                # current playlist as "Music"), which we exclude — reacting to it
                # would collapse the view, so ignore anything not in the list.
                if current_pl in browser._playlist_names and current_pl != self._last_known_playlist:
                    self._last_known_playlist = current_pl
                    tracks = self._cache_get_playlist_tracks(current_pl)
                    if not tracks:
                        tracks = await self.client.get_playlist_tracks(current_pl)
                    browser.expand_playlist(current_pl, tracks)
            elif browser._mode == "albums":
                current_album = state["album"]
                if current_album and current_album != self._last_known_album:
                    self._last_known_album = current_album
                    if self._queue_kind == "album" and self._queue_name == current_album and self._queue_artist:
                        artist = self._queue_artist
                    else:
                        # Look up album artist from the browser's album list
                        matches = [a for n, a in browser._album_items if n == current_album]
                        if len(matches) == 1:
                            artist = matches[0]
                        elif matches:
                            # Multiple albums with same name; match track artist
                            track_artist = state.get("artist", "")
                            artist = next((a for a in matches if a == track_artist), matches[0])
                        else:
                            artist = ""
                    tracks = self._cache_get_album_tracks(current_album, artist)
                    if not tracks:
                        tracks = await self.client.get_album_tracks(current_album, artist)
                    browser.expand_album(current_album, tracks, artist)
        except Exception:
            # This runs on a 1s timer; an escaped exception would crash the app.
            _log.exception("State poll failed")
        finally:
            self._polling = False
            self._alert("poll_state done")

    async def _queue_play_index(self, idx: int) -> None:
        """Play the track at idx of the active queue (album or playlist)."""
        name = self._queue_track_list[idx]
        if self._queue_kind == "playlist":
            await self.client.play_playlist_track(self._queue_name, idx + 1)
        else:
            await self.client.play_album_track(self._queue_name, idx + 1, name, self._queue_artist)

    async def _handle_continuation(self, state: MusicState) -> None:
        """Advance to the next queued track when playback stops at a boundary.

        Apple Music doesn't auto-continue after a single-track album play or
        `play track N of <playlist>` (the track detaches into the library), so
        we drive it. The _queue_awaiting_play flag prevents a second "stopped"
        poll from double-advancing or prematurely clearing the queue before the
        new track starts.
        """
        if state["state"] == "playing":
            self._queue_awaiting_play = False
            self._queue_play_retries = 0
            track = state["track"]
            if track in self._queue_track_list:
                # Use current index if it still matches to handle duplicate track names;
                # otherwise find the next matching index after the current position.
                if (
                    self._queue_track_idx >= len(self._queue_track_list)
                    or self._queue_track_list[self._queue_track_idx] != track
                ):
                    for i, name in enumerate(self._queue_track_list):
                        if name == track and i >= self._queue_track_idx:
                            self._queue_track_idx = i
                            break
                    else:
                        self._queue_track_idx = next(
                            i for i, name in enumerate(self._queue_track_list) if name == track
                        )
        elif state["state"] == "stopped":
            now = time.monotonic()
            if self._queue_awaiting_play:
                # The advance command may have silently failed; retry the
                # same track, and give up continuation if it won't start.
                if now - self._queue_awaiting_since > 5.0:
                    if self._queue_play_retries >= 2:
                        self._alert("queue continue: giving up after failed retries")
                        self._queue_kind = ""
                        self._queue_awaiting_play = False
                    else:
                        self._queue_play_retries += 1
                        self._queue_awaiting_since = now
                        self._alert(f"queue continue: retry {self._queue_play_retries} for track {self._queue_track_idx + 1}")
                        await self._queue_play_index(self._queue_track_idx)
            elif self._queue_track_idx < len(self._queue_track_list) - 1:
                self._queue_track_idx += 1
                self._queue_awaiting_play = True
                self._queue_awaiting_since = now
                self._alert(f"queue continue: track {self._queue_track_idx + 1}/{len(self._queue_track_list)}")
                await self._queue_play_index(self._queue_track_idx)
            else:
                self._queue_kind = ""  # reached end of queue

    def _interpolate_position(self) -> None:
        if self._last_state is None:
            return
        if self._last_state["state"] == "playing":
            elapsed = time.monotonic() - self._last_poll
            interpolated = self._last_state["position"] + elapsed
            duration = self._last_state["duration"]
            if duration > 0:
                interpolated = min(interpolated, duration)
            np = self.query_one(NowPlaying)
            np.position = interpolated
            # Update lyrics scroll position
            if self._lyrics_visible and self._lyrics_synced and self._parsed_lyrics:
                idx = find_current_line(self._parsed_lyrics, interpolated)
                if idx != self._lyrics_current_line:
                    self._lyrics_current_line = idx
                    self._last_gap_bold_count = -1
                    self.query_one(LyricsOverlay).update_current_line(idx)
                # Gap animation update
                if idx in self._gap_lines and idx in self._gap_end_times:
                    gap_start = self._parsed_lyrics[idx][0]
                    gap_end = self._gap_end_times[idx]
                    gap_duration = gap_end - gap_start
                    if gap_duration > 0:
                        frac = max(0.0, min(1.0, (interpolated - gap_start) / gap_duration))
                        frame = min(3, int(frac * 4))
                        if frame != self._last_gap_bold_count:
                            self._last_gap_bold_count = frame
                            self.query_one(LyricsOverlay).update_gap_animation(idx, frame)

    async def _load_playlists_live(self) -> None:
        self._alert("load_playlists_live start")
        names = await self.client.get_playlists()
        # Don't clobber a good (cached) list with an empty result from a
        # transient osascript failure; only update when we actually got names.
        if names:
            self.query_one(PlaylistBrowser).set_playlists(names)
        self._alert(f"load_playlists_live done ({len(names)} playlists)")

    def _load_library_cached(self) -> None:
        self._alert("load_library_cached start")
        try:
            self._cache = LibraryCache()
        except Exception:
            _log.exception("Failed to init library cache")
            return

        browser = self.query_one(PlaylistBrowser)
        if not self._cache.is_empty():
            self._alert("cache hit — reading albums from SQLite")
            albums = self._cache.get_albums()
            browser.set_albums(albums)
            self._alert(f"cache loaded ({len(albums)} albums)")
        else:
            self._alert("cache empty — will populate in background")

        if self._cache.has_playlists():
            self._alert("cache hit — reading playlists from SQLite")
            playlists = self._cache.get_playlists()
            browser.set_playlists(playlists)
            self._alert(f"cache loaded ({len(playlists)} playlists)")

        # Always refresh playlist names live — a single cheap osascript call,
        # independent of the throttled track sync below — so playlists added or
        # removed since the last sync appear on every launch (the cached list,
        # if any, is painted first for instant display).
        self.run_worker(self._load_playlists_live(), group="playlists")

        self.run_worker(self._sync_library(), exclusive=True, group="sync")

    def _schedule_sync(self) -> None:
        self.run_worker(self._sync_library(), exclusive=True, group="sync")

    async def _sync_library(self) -> None:
        if self._syncing or self._cache is None:
            return
        self._syncing = True
        try:
            last = self._cache.get_last_sync()
            if last is not None:
                age = (datetime.now(timezone.utc) - last).total_seconds()
                if age < 300:  # skip if synced less than 5 minutes ago
                    self._alert(f"sync_library skipped (last sync {age:.0f}s ago)")
                    return
            self._alert("sync_library start (AppleScript bulk fetch)")
            loop = asyncio.get_running_loop()
            tracks = await self.client.get_all_tracks()
            self._alert(f"sync_library fetched {len(tracks)} tracks")
            if tracks:
                await loop.run_in_executor(None, self._cache.replace_all, tracks)
                self._alert("sync_library cache updated")
                albums = self._cache.get_albums()
                self.query_one(PlaylistBrowser).set_albums(albums)
                self._alert(f"sync_library albums done ({len(albums)} albums)")

            playlist_names = await self.client.get_playlists()
            self._alert(f"sync_library fetched {len(playlist_names)} playlist names")
            if playlist_names:
                playlists: dict[str, list[str]] = {}
                for name in playlist_names:
                    self._alert(f"loading tracks for {name}")
                    pl_tracks = await self.client.get_playlist_tracks(name)
                    playlists[name] = pl_tracks
                await loop.run_in_executor(None, self._cache.replace_playlists, playlists)
                self.query_one(PlaylistBrowser).set_playlists(playlist_names)
                self._alert(f"sync_library playlists done ({len(playlists)} playlists)")
        except Exception:
            _log.exception("Library sync failed")
            self._alert("sync_library FAILED")
        finally:
            self._syncing = False

    def _cache_get_album_tracks(self, album_name: str, artist: str = "") -> list[str] | None:
        if self._cache is None or self._cache.is_empty():
            return None
        return self._cache.get_album_tracks(album_name, artist)

    def _cache_get_playlist_tracks(self, playlist_name: str) -> list[str] | None:
        if self._cache is None or not self._cache.has_playlists():
            return None
        tracks = self._cache.get_playlist_tracks(playlist_name)
        return tracks or None

    async def on_playlist_browser_playlist_selected(
        self, message: PlaylistBrowser.PlaylistSelected
    ) -> None:
        # Playing the whole playlist establishes a native queue that continues
        # on its own, so no app-driven continuation is needed here.
        self._queue_kind = ""
        name = message.name
        await self.client.play_playlist(name)
        tracks = self._cache_get_playlist_tracks(name)
        if not tracks:
            tracks = await self.client.get_playlist_tracks(name)
        self._last_known_playlist = name
        self.query_one(PlaylistBrowser).expand_playlist(name, tracks)

    async def on_playlist_browser_track_selected(
        self, message: PlaylistBrowser.TrackSelected
    ) -> None:
        # `play track N of <playlist>` plays the right track but detaches it
        # into the library (no native continuation), so drive it ourselves.
        await self.client.play_playlist_track(message.playlist, message.track_index)
        await self._start_playlist_continuation(message.playlist, message.track_index - 1)

    def _set_queue(self, kind: str, name: str, tracks: list[str], start_idx: int, artist: str = "") -> None:
        self._queue_kind = kind
        self._queue_name = name
        self._queue_artist = artist
        self._queue_track_list = tracks
        self._queue_track_idx = start_idx
        self._queue_awaiting_play = False
        self._queue_play_retries = 0

    async def _start_album_continuation(self, album_name: str, start_idx: int = 0, artist: str = "") -> list[str]:
        """Set up album continuation tracking and return the track list."""
        tracks = self._cache_get_album_tracks(album_name, artist)
        if not tracks:
            tracks = await self.client.get_album_tracks(album_name, artist)
        self._set_queue("album", album_name, tracks, start_idx, artist)
        return tracks

    async def _start_playlist_continuation(self, playlist_name: str, start_idx: int = 0) -> list[str]:
        """Set up playlist continuation tracking and return the track list."""
        tracks = self._cache_get_playlist_tracks(playlist_name)
        if not tracks:
            tracks = await self.client.get_playlist_tracks(playlist_name)
        self._set_queue("playlist", playlist_name, tracks, start_idx)
        return tracks

    async def on_playlist_browser_album_selected(
        self, message: PlaylistBrowser.AlbumSelected
    ) -> None:
        name = message.name
        artist = message.artist
        await self.client.play_album(name, artist)
        tracks = await self._start_album_continuation(name, 0, artist)
        self.query_one(PlaylistBrowser).expand_album(name, tracks, artist)
        self._last_known_album = name

    async def on_playlist_browser_album_track_selected(
        self, message: PlaylistBrowser.AlbumTrackSelected
    ) -> None:
        await self.client.play_album_track(message.album, message.track_index, message.track_name, message.artist)
        await self._start_album_continuation(message.album, message.track_index - 1, message.artist)

    async def action_play_pause(self) -> None:
        await self.client.play_pause()

    async def action_next_track(self) -> None:
        if self._queue_kind and self._queue_track_list:
            if self._queue_track_idx < len(self._queue_track_list) - 1:
                self._queue_track_idx += 1
                await self._queue_play_index(self._queue_track_idx)
        else:
            await self.client.next_track()

    async def action_previous_track(self) -> None:
        if self._queue_kind and self._queue_track_list:
            if self._queue_track_idx > 0:
                self._queue_track_idx -= 1
                await self._queue_play_index(self._queue_track_idx)
        else:
            await self.client.previous_track()

    async def action_toggle_shuffle(self) -> None:
        current = self._last_state["shuffle"] if self._last_state else False
        await self.client.set_shuffle(not current)

    async def action_cycle_repeat(self) -> None:
        current = self._last_state["repeat"] if self._last_state else "off"
        next_mode = {"off": "all", "all": "one", "one": "off"}.get(current, "off")
        await self.client.set_repeat(next_mode)

    def action_toggle_browse_mode(self) -> None:
        browser = self.query_one(PlaylistBrowser)
        tabs = browser.query_one(Tabs)
        if browser._mode == "playlists":
            tabs.active = "tab-albums"
        else:
            tabs.active = "tab-playlists"

    def action_toggle_album_sort(self) -> None:
        browser = self.query_one(PlaylistBrowser)
        new_sort = browser.toggle_album_sort()
        self.notify(f"Albums: sort by {new_sort}", timeout=2)

    def action_cycle_theme(self) -> None:
        themes = list(self.available_themes.keys())
        current = themes.index(self.theme) if self.theme in themes else -1
        self.theme = themes[(current + 1) % len(themes)]
        self.notify(f"Theme: {self.theme}", timeout=2)
        self._config.theme = self.theme
        self._config.save()

    async def action_volume_up(self) -> None:
        current = self._last_state["volume"] if self._last_state else 50
        await self.client.set_volume(min(100, current + 5))

    async def action_volume_down(self) -> None:
        current = self._last_state["volume"] if self._last_state else 50
        await self.client.set_volume(max(0, current - 5))

    def action_toggle_airplay(self) -> None:
        picker = self.query_one(AirPlayPicker)
        opening = not picker.expanded
        if opening:
            self._close_lyrics()
            self._close_visualization()
        picker.expanded = opening

    def action_toggle_lyrics(self) -> None:
        self._lyrics_visible = not self._lyrics_visible
        if self._lyrics_visible:
            self._close_airplay()
            self._close_visualization()
        overlay = self.query_one(LyricsOverlay)
        overlay.set_class(self._lyrics_visible, "visible")
        if self._lyrics_visible:
            overlay._center()
            state = self._last_state
            if state and state["track"]:
                if state["track"] != self._lyrics_track or state["artist"] != self._lyrics_artist:
                    self._lyrics_current_line = -1
                    self.run_worker(self._load_lyrics(), group="lyrics")

    def action_cycle_visualization(self) -> None:
        """Cycle the visualization overlay: mirrored -> stacked -> side-by-side -> closed."""
        nxt = self._viz_index + 1
        self._viz_index = nxt if nxt < NUM_VIZ else -1
        overlay = self.query_one(VisualizationOverlay)
        visible = self._viz_index >= 0
        if visible:
            self._close_lyrics()
            self._close_airplay()
            overlay.show_viz(self._viz_index)
            overlay._center()
        overlay.set_class(visible, "visible")

    def _close_lyrics(self) -> None:
        """Hide the lyrics overlay if open."""
        if self._lyrics_visible:
            self._lyrics_visible = False
            self.query_one(LyricsOverlay).remove_class("visible")

    def _close_airplay(self) -> None:
        """Collapse the AirPlay picker if expanded."""
        picker = self.query_one(AirPlayPicker)
        if picker.expanded:
            picker.expanded = False

    def _close_visualization(self) -> None:
        """Hide the visualization overlay if open."""
        if self._viz_index >= 0:
            self._viz_index = -1
            self.query_one(VisualizationOverlay).remove_class("visible")

    def action_close_overlay(self) -> None:
        self._close_lyrics()
        self._close_airplay()
        self._close_visualization()

    def _reset_lyrics_state(self) -> None:
        """Clear parsed-lyrics state so stale lines aren't used after a miss or error."""
        self._parsed_lyrics = None
        self._lyrics_synced = False
        self._gap_lines = set()
        self._gap_end_times = {}
        self._last_gap_bold_count = -1

    async def _show_no_lyrics(self, overlay: LyricsOverlay, track: str, artist: str) -> None:
        """Reset lyrics state and display the 'no lyrics' placeholder."""
        self._reset_lyrics_state()
        await overlay.show_no_lyrics(track, artist)

    async def _load_lyrics(self) -> None:
        state = self._last_state
        if not state or not state["track"]:
            return
        track, artist, album = state["track"], state["artist"], state["album"]
        duration = state["duration"]

        self._lyrics_track = track
        self._lyrics_artist = artist
        self._lyrics_loading = True
        overlay = self.query_one(LyricsOverlay)
        await overlay.show_loading(track, artist)

        try:
            # Check cache first
            cached = None
            if self._cache is not None:
                cached = self._cache.get_lyrics(track, artist, album)

            if cached is not None:
                synced = cached["synced_lyrics"]
                plain = cached["plain_lyrics"]
            else:
                # Fetch from lrclib.net
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, fetch_lyrics, track, artist, album, duration
                )
                synced = result["synced_lyrics"]
                plain = result["plain_lyrics"]
                # Cache the result (including "not found")
                if self._cache is not None:
                    await loop.run_in_executor(
                        None, self._cache.store_lyrics, track, artist, album, synced, plain
                    )

            if synced:
                self._parsed_lyrics = insert_gap_lines(parse_lrc(synced))
                self._lyrics_synced = True
                # Compute gap metadata
                self._gap_lines = set()
                self._gap_end_times = {}
                for i, (ts, text) in enumerate(self._parsed_lyrics):
                    if text == GAP_SENTINEL:
                        self._gap_lines.add(i)
                        for j in range(i + 1, len(self._parsed_lyrics)):
                            if self._parsed_lyrics[j][1] != GAP_SENTINEL:
                                self._gap_end_times[i] = self._parsed_lyrics[j][0]
                                break
                lines = ["" if text == GAP_SENTINEL else text for _, text in self._parsed_lyrics]
            elif plain:
                lines = plain.splitlines()
                self._reset_lyrics_state()
            else:
                await self._show_no_lyrics(overlay, track, artist)
                return

            await overlay.set_lyrics(track, artist, lines, gap_indices=self._gap_lines)
            self._lyrics_current_line = -1
        except TransientLyricsError:
            # lrclib is unreachable -- show nothing for now, but don't cache the
            # outage as a miss so lyrics reappear once the service recovers.
            _log.info("lrclib.net unavailable; skipping cache for %r / %r", track, artist)
            await self._show_no_lyrics(overlay, track, artist)
        except Exception:
            _log.exception("Failed to load lyrics for %r / %r", track, artist)
            await self._show_no_lyrics(overlay, track, artist)
        finally:
            self._lyrics_loading = False

    async def on_air_play_picker_picker_opened(self, message: AirPlayPicker.PickerOpened) -> None:
        self._close_lyrics()
        self._close_visualization()
        devices = await self.client.get_airplay_devices()
        self.query_one(AirPlayPicker).devices = devices

    async def on_air_play_picker_device_toggled(self, message: AirPlayPicker.DeviceToggled) -> None:
        await self.client.set_airplay_device_selected(message.device_index, message.selected)
        devices = await self.client.get_airplay_devices()
        self.query_one(AirPlayPicker).devices = devices

    def action_show_help(self) -> None:
        help_text = (
            "[b]Keyboard Shortcuts[/b]\n"
            "\n"
            "  [b]space[/b]     Play / Pause\n"
            "  [b]\u2192[/b] / [b]l[/b]   Next track\n"
            "  [b]\u2190[/b] / [b]h[/b]   Previous track\n"
            "  [b]s[/b]         Toggle shuffle\n"
            "  [b]r[/b]         Cycle repeat (off \u2192 all \u2192 one)\n"
            "  [b]tab[/b]       Toggle playlists / albums\n"
            "  [b]a[/b]         Toggle album sort (title / artist)\n"
            "  [b]o[/b]         AirPlay output\n"
            "  [b]y[/b]         Lyrics\n"
            "  [b]t[/b]         Cycle theme\n"
            "  [b]+[/b] / [b]=[/b]   Volume up 5\n"
            "  [b]-[/b]         Volume down 5\n"
            "  [b]?[/b]         Show this help\n"
            "  [b]q[/b]         Quit"
        )
        self.notify(help_text, title="Help", timeout=8)

    def on_click(self, event: Click) -> None:
        picker = self.query_one(AirPlayPicker)
        if not picker.expanded:
            return
        # Check if click is on overlay device row
        try:
            overlay = self.screen.query_one(AirPlayOverlay)
            for row in overlay.query(".ap-row"):
                if hasattr(row, "_airplay_index") and row.region.contains_point(event.screen_offset):
                    new_selected = not row._airplay_selected
                    picker.post_message(AirPlayPicker.DeviceToggled(row._airplay_index, new_selected))
                    event.stop()
                    return
            # Close if click is outside both button and overlay
            if not picker.region.contains_point(event.screen_offset) and not overlay.region.contains_point(event.screen_offset):
                picker.expanded = False
        except Exception:
            picker.expanded = False

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        actions = {
            "btn-play": "play_pause",
            "btn-prev": "previous_track",
            "btn-next": "next_track",
            "btn-shuffle": "toggle_shuffle",
            "btn-repeat": "cycle_repeat",
        }
        action = actions.get(button_id)
        if action:
            await self.run_action(action)
            self.screen.set_focus(None)

    async def on_lyrics_overlay_lyric_line_clicked(self, message: LyricsOverlay.LyricLineClicked) -> None:
        if self._lyrics_synced and self._parsed_lyrics is not None:
            timestamp = self._parsed_lyrics[message.line_index][0]
            await self.client.set_position(timestamp)

    async def on_now_playing_seek_request(self, message: NowPlaying.SeekRequest) -> None:
        await self.client.set_position(message.position)

    async def on_volume_bar_volume_set_request(self, message: VolumeBar.VolumeSetRequest) -> None:
        await self.client.set_volume(message.level)
