"""Lyrics overlay dialogue widget."""
from __future__ import annotations

from textual.containers import VerticalScroll
from textual.app import ComposeResult
from textual.events import Click, Resize
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label

from rich.text import Text


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
    LyricsOverlay .lyrics-gap-line {
        width: 100%;
        color: $text-muted;
    }
    LyricsOverlay .lyrics-gap-line.--current {
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
        self._lines: list[str] = []
        self._gap_indices: set[int] = set()

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
        self._lines = []
        self._gap_indices = set()

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

    async def set_lyrics(
        self, track: str, artist: str, lines: list[str], gap_indices: set[int] | None = None
    ) -> None:
        """Populate the overlay with lyric lines."""
        await self._clear_content()
        self._gap_indices = set(gap_indices) if gap_indices else set()
        await self.mount(Label(f"{track} \u2014 {artist}", classes="lyrics-title"))
        for i, line in enumerate(lines):
            if i in self._gap_indices:
                await self.mount(Label("", id=f"lyrics-line-{i}", classes="lyrics-gap-line"))
            else:
                text = line if line.strip() else " "
                await self.mount(Label(text, id=f"lyrics-line-{i}", classes="lyrics-line"))
        self._line_count = len(lines)
        self._lines = lines
        self.scroll_home(animate=False)

    class LyricLineClicked(Message):
        """Posted when a lyric line is clicked."""

        def __init__(self, line_index: int) -> None:
            super().__init__()
            self.line_index = line_index

    def on_click(self, event: Click) -> None:
        """Handle clicks on lyric lines to support seek."""
        widget = event.control
        if widget is not None and widget.id and widget.id.startswith("lyrics-line-"):
            try:
                index = int(widget.id.removeprefix("lyrics-line-"))
            except ValueError:
                return
            self.post_message(self.LyricLineClicked(index))
            event.stop()

    def update_current_line(self, index: int) -> None:
        """Highlight the current line and scroll it into view."""
        if index == self._current_idx:
            return
        # Remove highlight from previous line
        if 0 <= self._current_idx < self._line_count:
            try:
                prev = self.query_one(f"#lyrics-line-{self._current_idx}", Label)
                prev.remove_class("--current")
                if self._current_idx in self._gap_indices:
                    prev.update("")
            except Exception:
                pass
        self._current_idx = index
        # Add highlight to new line
        if 0 <= index < self._line_count:
            try:
                cur = self.query_one(f"#lyrics-line-{index}", Label)
                cur.add_class("--current")
                # Scroll to next non-empty line so current line has visible context
                scroll_target = cur
                for next_idx in range(index + 1, self._line_count):
                    if self._lines[next_idx].strip():
                        try:
                            scroll_target = self.query_one(f"#lyrics-line-{next_idx}", Label)
                        except Exception:
                            pass
                        break
                scroll_target.scroll_visible(animate=False)
            except Exception:
                pass

    _GAP_FRAMES = ("- - -", "* - -", "* * -", "* * *")

    def update_gap_animation(self, idx: int, frame: int) -> None:
        """Update the gap indicator to the given animation frame (0-3)."""
        try:
            label = self.query_one(f"#lyrics-line-{idx}", Label)
            label.update(self._GAP_FRAMES[frame])
        except Exception:
            pass
