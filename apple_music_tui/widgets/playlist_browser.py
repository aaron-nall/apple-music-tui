from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView


class PlaylistBrowser(Widget):
    """Scrollable playlist list; selecting an item posts PlaylistSelected."""

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
    """

    _playlist_names: list[str]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._playlist_names = []

    def compose(self) -> ComposeResult:
        yield ListView()

    def set_playlists(self, names: list[str]) -> None:
        self._playlist_names = list(names)
        lv = self.query_one(ListView)
        lv.clear()
        for name in names:
            lv.append(ListItem(Label(name)))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lv = self.query_one(ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._playlist_names):
            self.post_message(self.PlaylistSelected(self._playlist_names[idx]))

    class PlaylistSelected(Message):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name
