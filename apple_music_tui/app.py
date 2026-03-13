from __future__ import annotations

import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button

from apple_music_tui.config import load_config
from apple_music_tui.music_client import MusicClient
from apple_music_tui.themes import CUSTOM_THEMES
from apple_music_tui.widgets.controls import Controls, VolumeBar
from apple_music_tui.widgets.now_playing import NowPlaying
from apple_music_tui.widgets.playlist_browser import PlaylistBrowser
from apple_music_tui.widgets.status_bar import StatusBar


class AppleMusicApp(App):
    """Apple Music TUI controller."""

    TITLE = "Apple Music TUI"

    CSS = """
    Screen {
        background: $surface;
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
        Binding("plus,equal", "volume_up", "Vol+"),
        Binding("minus", "volume_down", "Vol-"),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "show_help", "Help", priority=True),
    ]

    def __init__(self) -> None:
        self._config = load_config()
        super().__init__()
        self.client = MusicClient()
        self._last_poll: float = 0
        self._last_state: dict = {}
        self._polling: bool = False
        self._last_known_playlist: str = ""  # tracks last auto-expanded playlist

    def compose(self) -> ComposeResult:
        with Vertical(id="main-container"):
            yield NowPlaying()
            yield Controls()
        yield PlaylistBrowser()
        yield StatusBar()

    def on_mount(self) -> None:
        for t in CUSTOM_THEMES:
            self.register_theme(t)
        saved = self._config.theme
        if saved in self.available_themes:
            self.theme = saved
        self.call_later(self._poll_state)
        self.call_later(self._load_playlists)
        self.call_later(self.screen.set_focus, None)
        self.set_interval(1.0, self._poll_state)
        self.set_interval(0.25, self._interpolate_position)

    async def _poll_state(self) -> None:
        if self._polling:
            return
        self._polling = True
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
            browser.set_current_track(state["track"])

            # Auto-expand if Music is playing a playlist we don't have expanded yet
            current_pl = state.get("current_playlist", "")
            if current_pl and current_pl != self._last_known_playlist:
                self._last_known_playlist = current_pl
                tracks = await self.client.get_playlist_tracks(current_pl)
                browser.expand_playlist(current_pl, tracks)
        finally:
            self._polling = False

    def _interpolate_position(self) -> None:
        if not self._last_state:
            return
        if self._last_state.get("state") == "playing":
            elapsed = time.monotonic() - self._last_poll
            interpolated = self._last_state["position"] + elapsed
            duration = self._last_state["duration"]
            if duration > 0:
                interpolated = min(interpolated, duration)
            np = self.query_one(NowPlaying)
            np.position = interpolated

    async def _load_playlists(self) -> None:
        names = await self.client.get_playlists()
        self.query_one(PlaylistBrowser).set_playlists(names)

    async def on_playlist_browser_playlist_selected(
        self, message: PlaylistBrowser.PlaylistSelected
    ) -> None:
        name = message.name
        await self.client.play_playlist(name)
        tracks = await self.client.get_playlist_tracks(name)
        self._last_known_playlist = name
        self.query_one(PlaylistBrowser).expand_playlist(name, tracks)

    async def on_playlist_browser_track_selected(
        self, message: PlaylistBrowser.TrackSelected
    ) -> None:
        await self.client.play_playlist_track(message.playlist, message.track_index)

    async def action_play_pause(self) -> None:
        await self.client.play_pause()

    async def action_next_track(self) -> None:
        await self.client.next_track()

    async def action_previous_track(self) -> None:
        await self.client.previous_track()

    async def action_toggle_shuffle(self) -> None:
        current = self._last_state.get("shuffle", False)
        await self.client.set_shuffle(not current)

    async def action_cycle_repeat(self) -> None:
        current = self._last_state.get("repeat", "off")
        next_mode = {"off": "all", "all": "one", "one": "off"}[current]
        await self.client.set_repeat(next_mode)

    def action_cycle_theme(self) -> None:
        themes = list(self.available_themes.keys())
        current = themes.index(self.theme) if self.theme in themes else -1
        self.theme = themes[(current + 1) % len(themes)]
        self.notify(f"Theme: {self.theme}", timeout=2)
        self._config.theme = self.theme
        self._config.save()

    async def action_volume_up(self) -> None:
        current = self._last_state.get("volume", 50)
        await self.client.set_volume(min(100, current + 5))

    async def action_volume_down(self) -> None:
        current = self._last_state.get("volume", 50)
        await self.client.set_volume(max(0, current - 5))

    def action_show_help(self) -> None:
        help_text = (
            "[b]Keyboard Shortcuts[/b]\n"
            "\n"
            "  [b]space[/b]     Play / Pause\n"
            "  [b]\u2192[/b] / [b]l[/b]   Next track\n"
            "  [b]\u2190[/b] / [b]h[/b]   Previous track\n"
            "  [b]s[/b]         Toggle shuffle\n"
            "  [b]r[/b]         Cycle repeat (off \u2192 all \u2192 one)\n"
            "  [b]t[/b]         Cycle theme\n"
            "  [b]+[/b] / [b]=[/b]   Volume up 5\n"
            "  [b]-[/b]         Volume down 5\n"
            "  [b]?[/b]         Show this help\n"
            "  [b]q[/b]         Quit"
        )
        self.notify(help_text, title="Help", timeout=8)

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

    async def on_now_playing_seek_request(self, message: NowPlaying.SeekRequest) -> None:
        await self.client.set_position(message.position)

    async def on_volume_bar_volume_set_request(self, message: VolumeBar.VolumeSetRequest) -> None:
        await self.client.set_volume(message.level)
