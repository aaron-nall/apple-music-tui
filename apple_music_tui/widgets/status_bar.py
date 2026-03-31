from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

try:
    _VERSION = version("apple-music-tui")
except PackageNotFoundError:
    _VERSION = "dev"


class StatusBar(Widget):
    """Minimal status bar showing app status."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    status_text: reactive[str] = reactive("")

    def on_mount(self) -> None:
        self.status_text = f"Apple Music TUI v{_VERSION}  |  y: lyrics  ?: help  q: quit"

    def compose(self) -> ComposeResult:
        yield Label(self.status_text, id="status-label")

    def watch_status_text(self) -> None:
        try:
            self.query_one("#status-label", Label).update(self.status_text)
        except NoMatches:
            pass
