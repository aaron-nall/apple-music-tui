from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


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

    status_text: reactive[str] = reactive("Apple Music TUI  |  ?: help  q: quit")

    def compose(self) -> ComposeResult:
        yield Label(self.status_text, id="status-label")

    def watch_status_text(self) -> None:
        try:
            self.query_one("#status-label", Label).update(self.status_text)
        except Exception:
            pass
