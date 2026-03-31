"""Lyrics overlay dialogue widget."""
from __future__ import annotations

from textual.containers import VerticalScroll
from textual.app import ComposeResult
from textual.events import Resize
from textual.widget import Widget
from textual.widgets import Label


class LyricsOverlay(VerticalScroll):
    """Full-screen centered overlay for displaying lyrics."""

    DEFAULT_CSS = """
    LyricsOverlay {
        display: none;
        layer: overlay;
        width: 60%;
        height: 80%;
        background: $surface;
        border: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }
    LyricsOverlay.visible {
        display: block;
    }
    LyricsOverlay .lyrics-title {
        text-style: bold;
        color: $accent;
        width: 100%;
        margin-bottom: 1;
    }
    LyricsOverlay .lyrics-line {
        width: 100%;
        color: $text-muted;
    }
    LyricsOverlay .lyrics-line.--current {
        text-style: bold;
        color: $accent;
    }
    LyricsOverlay .lyrics-status {
        width: 100%;
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._current_idx: int = -1
        self._line_count: int = 0

    def on_mount(self) -> None:
        self._center()

    def on_resize(self, event: Resize) -> None:
        self._center()

    def _center(self) -> None:
        """Center the overlay on screen using offset."""
        try:
            sw, sh = self.screen.size
            # Compute actual pixel dimensions from percentage
            ow = int(sw * 0.6)
            oh = int(sh * 0.8)
            self.styles.offset = ((sw - ow) // 2, (sh - oh) // 2)
        except Exception:
            pass

    async def _clear_content(self) -> None:
        """Remove all children."""
        await self.remove_children()
        self._current_idx = -1
        self._line_count = 0

    async def show_loading(self, track: str, artist: str) -> None:
        """Display loading state."""
        await self._clear_content()
        await self.mount(Label(f"{track} \u2014 {artist}", classes="lyrics-title"))
        await self.mount(Label("Loading lyrics\u2026", classes="lyrics-status"))

    async def show_no_lyrics(self, track: str, artist: str) -> None:
        """Display no-lyrics-found state."""
        await self._clear_content()
        await self.mount(Label(f"{track} \u2014 {artist}", classes="lyrics-title"))
        await self.mount(Label("No lyrics available", classes="lyrics-status"))

    async def set_lyrics(self, track: str, artist: str, lines: list[str]) -> None:
        """Populate the overlay with lyric lines."""
        await self._clear_content()
        await self.mount(Label(f"{track} \u2014 {artist}", classes="lyrics-title"))
        for i, line in enumerate(lines):
            text = line if line.strip() else " "
            await self.mount(Label(text, id=f"lyrics-line-{i}", classes="lyrics-line"))
        self._line_count = len(lines)
        self.scroll_home(animate=False)

    def update_current_line(self, index: int) -> None:
        """Highlight the current line and scroll it into view."""
        if index == self._current_idx:
            return
        # Remove highlight from previous line
        if 0 <= self._current_idx < self._line_count:
            try:
                prev = self.query_one(f"#lyrics-line-{self._current_idx}", Label)
                prev.remove_class("--current")
            except Exception:
                pass
        self._current_idx = index
        # Add highlight to new line
        if 0 <= index < self._line_count:
            try:
                cur = self.query_one(f"#lyrics-line-{index}", Label)
                cur.add_class("--current")
                cur.scroll_visible(animate=False)
            except Exception:
                pass
