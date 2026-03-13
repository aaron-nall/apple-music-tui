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
        first_track_item: ListItem | None = None

        for pl_name in self._playlist_names:
            item = ListItem(Label(pl_name))
            lv.append(item)
            self._flat_items.append({"type": "playlist", "name": pl_name})

            if pl_name == self._expanded_playlist:
                for i, track in enumerate(self._track_names, start=1):
                    track_item = ListItem(Label(f"  {track}"))
                    lv.append(track_item)
                    self._flat_items.append({"type": "track", "name": track, "track_index": i})
                    if first_track_item is None:
                        first_track_item = track_item

        self._update_track_highlight()

        if first_track_item is not None:
            self.call_after_refresh(lv.scroll_to_widget, first_track_item, animate=False)

    def _update_track_highlight(self) -> None:
        lv = self.query_one(ListView)
        items = list(lv.children)
        for item, meta in zip(items, self._flat_items):
            if meta["type"] == "track" and meta["name"] == self._current_track:
                item.add_class("playing-track")
            else:
                item.remove_class("playing-track")

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
