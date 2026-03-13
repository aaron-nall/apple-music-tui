from __future__ import annotations

from rich.cells import cell_len
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Click, Resize
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ProgressBar


class ScrollingLabel(Widget):
    """A label that horizontally marquee-scrolls its text only when it overflows."""

    DEFAULT_CSS = """
    ScrollingLabel {
        width: 1fr;
        text-style: bold;
        overflow: hidden hidden;
    }
    """

    _SEP: str = "    ·    "
    _INTERVAL: float = 0.15   # seconds per character step
    _INITIAL_DELAY: int = 13  # ticks (~2 s) before scrolling starts

    text: reactive[str] = reactive("", layout=True)
    _offset: int = 0
    _delay: int = 0

    def on_mount(self) -> None:
        self.set_interval(self._INTERVAL, self._tick)

    def watch_text(self) -> None:
        self._offset = 0
        self._delay = 0
        self.refresh()

    def on_resize(self, event: Resize) -> None:
        self._offset = 0
        self._delay = 0
        self.refresh()

    def _tick(self) -> None:
        w = self.size.width
        if w <= 0 or not self.text:
            return
        if cell_len(self.text) <= w:
            return  # fits — nothing to scroll
        if self._delay < self._INITIAL_DELAY:
            self._delay += 1
            return
        full = self.text + self._SEP
        self._offset = (self._offset + 1) % len(full)
        self.refresh()

    def render(self) -> str:
        w = self.size.width
        if not self.text or w <= 0:
            return self.text
        if cell_len(self.text) <= w:
            return self.text
        full = self.text + self._SEP
        doubled = full * 2
        return doubled[self._offset : self._offset + w]


class NowPlaying(Widget):
    """Displays track info + progress bar."""

    DEFAULT_CSS = """
    NowPlaying {
        height: 4;
        padding: 0 1;
    }
    NowPlaying #track-row {
        height: 1;
    }
    NowPlaying #album-row {
        height: 1;
    }
    NowPlaying ScrollingLabel {
        width: 1fr;
        margin-right: 2;
    }
    NowPlaying #artist-name {
        width: auto;
        text-align: right;
        color: $text-muted;
    }
    NowPlaying #album-name {
        color: $text-muted;
    }
    NowPlaying #time-display {
        width: auto;
        text-align: right;
        color: $text-muted;
    }
    NowPlaying #progress-bar {
        height: 1;
        margin: 0 0;
    }
    NowPlaying #progress-bar > .bar--bar {
        color: $accent;
    }
    """

    track: reactive[str] = reactive("")
    artist: reactive[str] = reactive("")
    album: reactive[str] = reactive("")
    position: reactive[float] = reactive(0.0)
    duration: reactive[float] = reactive(0.0)
    state: reactive[str] = reactive("stopped")
    running: reactive[bool] = reactive(True)

    def compose(self) -> ComposeResult:
        with Horizontal(id="track-row"):
            yield ScrollingLabel(id="track-name")
            yield Label("", id="artist-name")
        with Horizontal(id="album-row"):
            yield ScrollingLabel(id="album-name")
            yield Label("", id="time-display")
        yield ProgressBar(id="progress-bar", total=100, show_eta=False, show_percentage=False)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"

    def watch_track(self) -> None:
        self._update_display()

    def watch_artist(self) -> None:
        self._update_display()

    def watch_album(self) -> None:
        self._update_display()

    def watch_position(self) -> None:
        self._update_time()

    def watch_duration(self) -> None:
        self._update_time()

    def watch_running(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        if not self.running:
            self.query_one("#track-name", ScrollingLabel).text = "Apple Music is not running"
            self.query_one("#artist-name", Label).update("")
            self.query_one("#album-name", ScrollingLabel).text = ""
            return
        if not self.track:
            self.query_one("#track-name", ScrollingLabel).text = "\u266b  Nothing playing"
            self.query_one("#artist-name", Label).update("")
            self.query_one("#album-name", ScrollingLabel).text = ""
            return
        self.query_one("#track-name", ScrollingLabel).text = f"\u266b  {self.track}"
        self.query_one("#artist-name", Label).update(self.artist)
        self.query_one("#album-name", ScrollingLabel).text = f"   {self.album}"

    def _update_time(self) -> None:
        if self.duration > 0:
            pos_str = self._fmt_time(self.position)
            dur_str = self._fmt_time(self.duration)
            self.query_one("#time-display", Label).update(f"[{pos_str} / {dur_str}]")
            progress = (self.position / self.duration) * 100
            self.query_one("#progress-bar", ProgressBar).update(progress=min(progress, 100))
        else:
            self.query_one("#time-display", Label).update("")
            self.query_one("#progress-bar", ProgressBar).update(progress=0)

    def on_click(self, event: Click) -> None:
        """Click-to-seek on the progress bar area only."""
        bar = self.query_one("#progress-bar", ProgressBar)
        bar_region = bar.region
        if bar_region and self.duration > 0:
            # Only respond to clicks within the progress bar's region
            if not (bar_region.y <= event.screen_y < bar_region.y + bar_region.height):
                return
            rel_x = event.screen_x - bar_region.x
            if not (0 <= rel_x < bar_region.width):
                return
            fraction = max(0.0, min(1.0, rel_x / max(bar_region.width, 1)))
            seek_to = fraction * self.duration
            self.post_message(self.SeekRequest(seek_to))

    class SeekRequest(Message):
        def __init__(self, position: float) -> None:
            super().__init__()
            self.position = position
