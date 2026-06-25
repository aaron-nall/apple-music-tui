from __future__ import annotations

import math

from rich.text import Text
from textual.widget import Widget

from apple_music_tui.widgets._meter_style import meter_colors

_N = 8          # LED segments per channel
_DB_FLOOR = -50.0  # dB below which the bar shows 0
_DB_CEIL  = -12.0  # dB at which the bar is full (normal music peaks ~–12 dBFS)


def _bar(level: float, colors: tuple[str, str, str]) -> Text:
    filled = 0
    if level > 0:
        db = 20.0 * math.log10(level)
        filled = min(_N, max(0, round((db - _DB_FLOOR) / (_DB_CEIL - _DB_FLOOR) * _N)))
    low, mid, peak = colors
    t = Text()
    for i in range(_N):
        if i < filled:
            color = low if i < 5 else (mid if i < 7 else peak)
            t.append("█", style=color)
        else:
            t.append("░", style="dim")
    return t


class VUMeter(Widget):
    """Horizontal LED-style stereo VU meter driven by the app's shared AudioMeter."""

    DEFAULT_CSS = """
    VUMeter {
        width: 1fr;
        height: 1;
        content-align: center middle;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._levels: tuple[float, float] = (0.0, 0.0)

    def on_mount(self) -> None:
        # The meter is owned and started by the app; poll it lazily so this
        # is robust to mount ordering and to the meter being unavailable.
        self.set_interval(1 / 10, self._poll)

    def _poll(self) -> None:
        meter = getattr(self.app, "audio_meter", None)
        if meter is None:
            return
        new = meter.levels
        if new != self._levels:
            self._levels = new
            self.refresh()

    def render(self) -> Text:
        colors = meter_colors(self.app)
        left, right = self._levels
        t = _bar(left, colors)
        t.append(" ")
        t.append_text(_bar(right, colors))
        return t
