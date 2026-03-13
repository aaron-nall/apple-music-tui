from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label


class VolumeBar(Widget):
    """Volume display: clickable icon (mute toggle) + clickable bar (set level) + number."""

    DEFAULT_CSS = """
    VolumeBar {
        height: 1;
        width: auto;
        layout: horizontal;
    }
    VolumeBar #vol-icon {
        width: auto;
    }
    VolumeBar #vol-icon:hover {
        text-style: bold;
    }
    VolumeBar #vol-bar {
        width: 10;
    }
    VolumeBar #vol-bar:hover {
        text-style: bold;
    }
    VolumeBar #vol-num {
        width: 4;
        text-align: right;
    }
    """

    volume: reactive[int] = reactive(50)

    def __init__(self) -> None:
        super().__init__()
        self._pre_mute_volume: int = 50

    def compose(self) -> ComposeResult:
        yield Label("\U0001f50a ", id="vol-icon")
        yield Label("", id="vol-bar")
        yield Label("50", id="vol-num")

    def watch_volume(self) -> None:
        filled = round(self.volume / 100 * 8)
        empty = 8 - filled
        bar_str = "\u2588" * filled + "\u2591" * empty
        try:
            self.query_one("#vol-bar", Label).update(bar_str)
            self.query_one("#vol-num", Label).update(str(self.volume))
            icon = "\U0001f507 " if self.volume == 0 else "\U0001f50a "
            self.query_one("#vol-icon", Label).update(icon)
        except NoMatches:
            pass

    def on_click(self, event: Click) -> None:
        icon = self.query_one("#vol-icon", Label)
        bar = self.query_one("#vol-bar", Label)

        icon_region = icon.region
        bar_region = bar.region

        # Click on speaker icon → toggle mute
        if icon_region and icon_region.x <= event.screen_x < icon_region.x + icon_region.width:
            if self.volume > 0:
                self._pre_mute_volume = self.volume
                self.post_message(self.VolumeSetRequest(0))
            else:
                self.post_message(self.VolumeSetRequest(self._pre_mute_volume or 50))
            return

        # Click on volume bar → set level based on position
        if bar_region and bar_region.width > 0:
            rel_x = event.screen_x - bar_region.x
            if 0 <= rel_x < bar_region.width:
                fraction = (rel_x + 0.5) / bar_region.width
                level = round(max(0, min(100, fraction * 100)))
                self.post_message(self.VolumeSetRequest(level))

    class VolumeSetRequest(Message):
        def __init__(self, level: int) -> None:
            super().__init__()
            self.level = level


class Controls(Widget):
    """Playback control bar: shuffle, prev, play/pause, next, repeat, volume."""

    DEFAULT_CSS = """
    Controls {
        height: 2;
        align: center middle;
        padding: 0 1;
    }
    Controls #control-row {
        height: 1;
        align: center middle;
        width: 100%;
    }
    Controls .control-spacer {
        width: 1fr;
    }
    Controls Button {
        min-width: 5;
        height: 1;
        border: none;
        background: transparent;
        padding: 0 1;
    }
    Controls Button:hover {
        background: $surface-lighten-2;
    }
    Controls #btn-shuffle.active {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    Controls #btn-repeat.active {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    Controls #btn-play {
        text-style: bold;
        min-width: 5;
    }
    """

    playing: reactive[bool] = reactive(False)
    shuffle: reactive[bool] = reactive(False)
    repeat_mode: reactive[str] = reactive("off")
    volume: reactive[int] = reactive(50)

    def compose(self) -> ComposeResult:
        with Horizontal(id="control-row"):
            yield Label("", classes="control-spacer")
            yield Button("\u21c4", id="btn-shuffle")
            yield Button("|\u25c0\u25c0", id="btn-prev")
            yield Button("\u25b6", id="btn-play")
            yield Button("\u25b6\u25b6|", id="btn-next")
            yield Button("\u21ba", id="btn-repeat")
            yield Label(" ", classes="control-spacer")
            yield VolumeBar()

    def watch_playing(self) -> None:
        btn = self.query_one("#btn-play", Button)
        btn.label = "\u23f8" if self.playing else "\u25b6"

    def watch_shuffle(self) -> None:
        btn = self.query_one("#btn-shuffle", Button)
        btn.set_class(self.shuffle, "active")

    def watch_repeat_mode(self) -> None:
        btn = self.query_one("#btn-repeat", Button)
        if self.repeat_mode == "one":
            btn.label = "\u21ba\u00b9"
            btn.set_class(True, "active")
        elif self.repeat_mode == "all":
            btn.label = "\u21ba"
            btn.set_class(True, "active")
        else:
            btn.label = "\u21ba"
            btn.set_class(False, "active")

    def watch_volume(self) -> None:
        self.query_one(VolumeBar).volume = self.volume
