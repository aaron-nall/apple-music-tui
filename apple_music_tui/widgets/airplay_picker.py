from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label


class AirPlayOverlay(Vertical):
    """Overlay panel mounted directly on the Screen so it isn't clipped."""

    DEFAULT_CSS = """
    AirPlayOverlay {
        display: none;
        layer: overlay;
        width: 36;
        max-height: 14;
        background: $surface;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    AirPlayOverlay.visible {
        display: block;
    }
    AirPlayOverlay .ap-header {
        text-style: bold;
        width: 100%;
        padding: 0 0 0 0;
        color: $accent;
    }
    AirPlayOverlay .ap-row {
        width: 100%;
        height: 1;
        padding: 0;
    }
    AirPlayOverlay .ap-row:hover {
        background: $accent 30%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("AirPlay Devices", classes="ap-header")


class AirPlayPicker(Widget):
    """AirPlay device selector: toggle button + expandable overlay with checkboxes."""

    DEFAULT_CSS = """
    AirPlayPicker {
        width: auto;
        height: auto;
    }
    AirPlayPicker #btn-airplay {
        min-width: 5;
        height: 1;
        border: none;
        background: transparent;
        padding: 0 1;
        &:focus { background: transparent; }
    }
    AirPlayPicker #btn-airplay:hover {
        background: $surface-lighten-2;
    }
    """

    expanded: reactive[bool] = reactive(False)
    devices: reactive[list] = reactive(list, always_update=True)

    class DeviceToggled(Message):
        def __init__(self, device_index: int, selected: bool) -> None:
            super().__init__()
            self.device_index = device_index
            self.selected = selected

    class PickerOpened(Message):
        pass

    def compose(self) -> ComposeResult:
        yield Button(")))", id="btn-airplay")

    def _get_overlay(self) -> AirPlayOverlay | None:
        try:
            return self.screen.query_one(AirPlayOverlay)
        except Exception:
            return None

    def _ensure_overlay(self) -> AirPlayOverlay:
        overlay = self._get_overlay()
        if overlay is None:
            overlay = AirPlayOverlay()
            self.screen.mount(overlay)
        return overlay

    def watch_expanded(self) -> None:
        overlay = self._ensure_overlay()
        overlay.set_class(self.expanded, "visible")
        if self.expanded:
            self._position_overlay(overlay)
            self.post_message(self.PickerOpened())

    def _position_overlay(self, overlay: AirPlayOverlay) -> None:
        """Position overlay below the button."""
        try:
            btn = self.query_one("#btn-airplay", Button)
            region = btn.region
            overlay.styles.offset = (region.x, region.y + region.height)
        except Exception:
            pass

    def watch_devices(self) -> None:
        overlay = self._get_overlay()
        if overlay is None:
            return
        # Remove old rows
        for row in list(overlay.query(".ap-row")):
            row.remove()
        # Add new rows
        if not self.devices:
            overlay.mount(Label("  No devices found", classes="ap-row"))
            return
        for dev in self.devices:
            check = "\u2611" if dev["selected"] else "\u2610"
            kind = dev["kind"]
            label_text = f" {check} {dev['name']} ({kind})"
            row = Label(label_text, classes="ap-row")
            row._airplay_index = dev["index"]
            row._airplay_selected = dev["selected"]
            overlay.mount(row)
        if self.expanded:
            self._position_overlay(overlay)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-airplay":
            self.expanded = not self.expanded
            event.button.blur()
            event.stop()
