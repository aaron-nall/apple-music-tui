from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView


class PlaylistBrowser(Widget):
    """Scrollable playlist list with expandable track view."""

    DEFAULT_CSS = """
    PlaylistBrowser {
        height: 1fr;
        width: 1fr;
        border-top: solid $accent-darken-2;
        padding: 0 0;
    }
    PlaylistBrowser > ListView {
        height: 1fr;
        width: 1fr;
        background: transparent;
        padding: 0 1;
    }
    PlaylistBrowser > ListView > ListItem {
        background: transparent;
        padding: 0 1;
    }
    PlaylistBrowser > ListView > ListItem.--highlight {
        background: $accent 15%;
    }
    PlaylistBrowser > ListView:focus > ListItem.--highlight {
        background: $accent 30%;
    }
    PlaylistBrowser > ListView > ListItem.playing-track {
        background: $accent 40%;
        text-style: bold;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._playlist_names: list[str] = []
        self._expanded_playlist: str | None = None
        self._track_names: list[str] = []
        self._current_track: str | None = None
        # Each entry: {"type": "playlist"|"track", "name": str, "track_index": int}
        self._flat_items: list[dict] = []
        self._highlighted_idx: int | None = None  # index of the currently highlighted track item

    def compose(self) -> ComposeResult:
        yield ListView()

    def set_playlists(self, names: list[str]) -> None:
        self._playlist_names = list(names)
        self._rebuild_list()

    def expand_playlist(self, name: str, tracks: list[str]) -> None:
        """Expand a playlist to show its tracks inline."""
        self._expanded_playlist = name
        self._track_names = list(tracks)
        self._rebuild_list()

    def collapse(self) -> None:
        """Collapse back to plain playlist list."""
        self._expanded_playlist = None
        self._track_names = []
        self._rebuild_list()

    def set_current_track(self, track_name: str | None) -> None:
        """Update the highlighted playing track (called each poll cycle)."""
        if track_name == self._current_track:
            return
        self._current_track = track_name
        self._update_track_highlight()

    def _rebuild_list(self) -> None:
        lv = self.query_one(ListView)
        lv.clear()
        self._flat_items = []
        self._highlighted_idx = None  # items are recreated; reset so _update_track_highlight re-applies
        expanded_playlist_item: ListItem | None = None

        for pl_name in self._playlist_names:
            item = ListItem(Label(pl_name))
            lv.append(item)
            self._flat_items.append({"type": "playlist", "name": pl_name})

            if pl_name == self._expanded_playlist:
                expanded_playlist_item = item
                for i, track in enumerate(self._track_names, start=1):
                    track_item = ListItem(Label(f"  {track}"))
                    lv.append(track_item)
                    self._flat_items.append({"type": "track", "name": track, "track_index": i})

        self._update_track_highlight()

        if self._expanded_playlist in self._playlist_names:
            # Scroll so the playlist header sits at the top of the view.
            # Each ListItem is 1 line tall, so the row index == the Y offset in cells.
            pl_row = self._playlist_names.index(self._expanded_playlist)
            self.call_after_refresh(lv.scroll_to, 0, pl_row, animate=False)

    def _update_track_highlight(self) -> None:
        # Find the index of the track that should be highlighted.
        new_idx: int | None = None
        for i, meta in enumerate(self._flat_items):
            if meta["type"] == "track" and meta["name"] == self._current_track:
                new_idx = i
                break

        if new_idx == self._highlighted_idx:
            return  # nothing changed — skip all DOM work

        lv = self.query_one(ListView)
        items = list(lv.children)

        # Remove highlight from the previously highlighted item (O(1) DOM update).
        if self._highlighted_idx is not None and self._highlighted_idx < len(items):
            items[self._highlighted_idx].remove_class("playing-track")

        # Apply highlight to the new item (O(1) DOM update).
        if new_idx is not None and new_idx < len(items):
            items[new_idx].add_class("playing-track")

        self._highlighted_idx = new_idx

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lv = self.query_one(ListView)
        idx = lv.index
        if idx is None or idx >= len(self._flat_items):
            return
        meta = self._flat_items[idx]
        if meta["type"] == "playlist":
            self.post_message(self.PlaylistSelected(meta["name"]))
        elif meta["type"] == "track" and self._expanded_playlist:
            self.post_message(self.TrackSelected(self._expanded_playlist, meta["track_index"]))

    class PlaylistSelected(Message):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    class TrackSelected(Message):
        def __init__(self, playlist: str, track_index: int) -> None:
            super().__init__()
            self.playlist = playlist
            self.track_index = track_index
