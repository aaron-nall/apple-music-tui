from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Tab, Tabs


class PlaylistBrowser(Widget):
    """Scrollable browser with tabs for playlists and albums."""

    DEFAULT_CSS = """
    PlaylistBrowser {
        height: 1fr;
        width: 1fr;
        border-top: solid $accent-darken-2;
        padding: 0 0;
    }
    PlaylistBrowser > Tabs {
        dock: top;
        height: 3;
        background: $surface;
    }
    PlaylistBrowser > #sort-label {
        height: 1;
        width: 1fr;
        text-align: right;
        padding: 0 2;
        color: $text-muted;
        display: none;
    }
    PlaylistBrowser > #sort-label.visible {
        display: block;
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
        self._mode: str = "playlists"  # "playlists" | "albums"
        # Playlist state
        self._playlist_names: list[str] = []
        self._expanded_playlist: str | None = None
        self._playlist_tracks: list[str] = []
        # Album state
        self._album_items: list[tuple[str, str]] = []  # (album_name, artist)
        self._album_sort: str = "title"  # "title" | "artist"
        self._expanded_album: str | None = None
        self._expanded_album_artist: str = ""
        self._album_tracks: list[str] = []
        # Shared state
        self._current_track: str | None = None
        self._current_album: str | None = None
        # Each entry: {"type": "playlist"|"track"|"album", "name": str, "track_index": int, "album_name": str}
        self._flat_items: list[dict] = []
        self._highlighted_idx: int | None = None

    def compose(self) -> ComposeResult:
        yield Tabs(
            Tab("Playlists", id="tab-playlists"),
            Tab("Albums", id="tab-albums"),
        )
        yield Label(self._sort_label_text(), id="sort-label")
        yield ListView()

    def _sort_label_text(self) -> str:
        return f"↑↓ {self._album_sort}"

    def on_click(self, event) -> None:
        if self._mode == "albums" and event.widget and event.widget.id == "sort-label":
            self.toggle_album_sort()

    def _update_sort_label(self) -> None:
        label = self.query_one("#sort-label", Label)
        label.update(self._sort_label_text())
        if self._mode == "albums":
            label.add_class("visible")
        else:
            label.remove_class("visible")

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        new_mode = "albums" if event.tab.id == "tab-albums" else "playlists"
        if new_mode != self._mode:
            self._mode = new_mode
            self._rebuild_list()
        self._update_sort_label()

    # --- Playlist methods ---

    def set_playlists(self, names: list[str]) -> None:
        self._playlist_names = list(names)
        if self._mode == "playlists":
            self._rebuild_list()

    def expand_playlist(self, name: str, tracks: list[str]) -> None:
        self._expanded_playlist = name
        self._playlist_tracks = list(tracks)
        if self._mode == "playlists":
            self._rebuild_list()

    def collapse_playlist(self) -> None:
        self._expanded_playlist = None
        self._playlist_tracks = []
        if self._mode == "playlists":
            self._rebuild_list()

    # --- Album methods ---

    def set_albums(self, albums: list[tuple[str, str]]) -> None:
        self._album_items = list(albums)
        if self._mode == "albums":
            self._rebuild_list()

    def expand_album(self, album_name: str, tracks: list[str], artist: str = "") -> None:
        self._expanded_album = album_name
        self._expanded_album_artist = artist
        self._album_tracks = list(tracks)
        if self._mode == "albums":
            self._rebuild_list()

    def collapse_album(self) -> None:
        self._expanded_album = None
        self._expanded_album_artist = ""
        self._album_tracks = []
        if self._mode == "albums":
            self._rebuild_list()

    def toggle_album_sort(self) -> str:
        """Toggle between sorting by title and artist. Returns the new sort key."""
        self._album_sort = "artist" if self._album_sort == "title" else "title"
        if self._mode == "albums":
            self._rebuild_list()
        self._update_sort_label()
        return self._album_sort

    # --- Shared methods ---

    def set_current_track(self, track_name: str | None, album_name: str | None = None) -> None:
        if track_name == self._current_track and album_name == self._current_album:
            return
        self._current_track = track_name
        self._current_album = album_name
        self._update_track_highlight()

    def _rebuild_list(self) -> None:
        lv = self.query_one(ListView)
        lv.clear()
        self._flat_items = []
        self._highlighted_idx = None

        if self._mode == "playlists":
            self._build_playlist_list(lv)
        else:
            self._build_album_list(lv)

        self._update_track_highlight()

    def _build_playlist_list(self, lv: ListView) -> None:
        expanded_item: ListItem | None = None
        for pl_name in self._playlist_names:
            item = ListItem(Label(pl_name))
            lv.append(item)
            self._flat_items.append({"type": "playlist", "name": pl_name})

            if pl_name == self._expanded_playlist:
                expanded_item = item
                for i, track in enumerate(self._playlist_tracks, start=1):
                    track_item = ListItem(Label(f"  {track}"))
                    lv.append(track_item)
                    self._flat_items.append({"type": "track", "name": track, "track_index": i})

        if self._expanded_playlist in self._playlist_names:
            pl_row = self._playlist_names.index(self._expanded_playlist)
            self.call_after_refresh(lv.scroll_to, 0, pl_row, animate=False)

    def _build_album_list(self, lv: ListView) -> None:
        if self._album_sort == "artist":
            sorted_albums = sorted(self._album_items, key=lambda x: x[1].lower())
        else:
            sorted_albums = sorted(self._album_items, key=lambda x: x[0].lower())
        for album_name, artist in sorted_albums:
            display = f"{album_name} - {artist}" if artist else album_name
            item = ListItem(Label(display))
            lv.append(item)
            self._flat_items.append({"type": "album", "name": album_name, "artist": artist})

            if album_name == self._expanded_album and artist == self._expanded_album_artist:
                for i, track in enumerate(self._album_tracks, start=1):
                    track_item = ListItem(Label(f"  {track}"))
                    lv.append(track_item)
                    self._flat_items.append({"type": "track", "name": track, "track_index": i, "album_name": album_name})

        if self._expanded_album:
            for idx, (aname, aartist) in enumerate(sorted_albums):
                if aname == self._expanded_album and aartist == self._expanded_album_artist:
                    self.call_after_refresh(lv.scroll_to, 0, idx, animate=False)
                    break

    def _update_track_highlight(self) -> None:
        new_idx: int | None = None
        for i, meta in enumerate(self._flat_items):
            if meta["type"] != "track" or meta["name"] != self._current_track:
                continue
            if self._mode == "albums" and self._current_album and meta.get("album_name") != self._current_album:
                continue
            new_idx = i
            break

        if new_idx == self._highlighted_idx:
            return

        lv = self.query_one(ListView)
        items = list(lv.children)

        if self._highlighted_idx is not None and self._highlighted_idx < len(items):
            items[self._highlighted_idx].remove_class("playing-track")

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
        elif meta["type"] == "album":
            self.post_message(self.AlbumSelected(meta["name"], meta.get("artist", "")))
        elif meta["type"] == "track":
            if self._mode == "playlists" and self._expanded_playlist:
                self.post_message(self.TrackSelected(self._expanded_playlist, meta["track_index"]))
            elif self._mode == "albums" and meta.get("album_name"):
                album_meta = next((m for m in self._flat_items if m["type"] == "album" and m["name"] == meta["album_name"]), None)
                artist = album_meta.get("artist", "") if album_meta else ""
                self.post_message(self.AlbumTrackSelected(meta["album_name"], meta["track_index"], meta["name"], artist))

    class PlaylistSelected(Message):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    class TrackSelected(Message):
        def __init__(self, playlist: str, track_index: int) -> None:
            super().__init__()
            self.playlist = playlist
            self.track_index = track_index

    class AlbumSelected(Message):
        def __init__(self, name: str, artist: str = "") -> None:
            super().__init__()
            self.name = name
            self.artist = artist

    class AlbumTrackSelected(Message):
        def __init__(self, album: str, track_index: int, track_name: str = "", artist: str = "") -> None:
            super().__init__()
            self.album = album
            self.track_index = track_index
            self.track_name = track_name
            self.artist = artist
