from __future__ import annotations

import math

from rich.text import Text
from textual.widget import Widget

from apple_music_tui.audio_meter import AudioMeter, AudioMeterError

_N = 8          # LED segments per channel
_DB_FLOOR = -50.0  # dB below which the bar shows 0
_DB_CEIL  = -12.0  # dB at which the bar is full (normal music peaks ~–12 dBFS)

_THEME_COLORS: dict[str, tuple[str, str, str]] = {
    "amber-terminal": ("#7A4F00", "#CC8800", "#FFCC33"),
    "green-terminal": ("#006600", "#00CC00", "#66FF66"),
}
_DEFAULT_COLORS: tuple[str, str, str] = ("green", "yellow", "red")


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
    """Horizontal LED-style stereo VU meter driven by AudioMeter (ScreenCaptureKit)."""

    DEFAULT_CSS = """
    VUMeter {
        width: 1fr;
        height: 1;
        content-align: center middle;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._meter: AudioMeter | None = None
        self._levels: tuple[float, float] = (0.0, 0.0)

    def on_mount(self) -> None:
        meter = AudioMeter()
        try:
            meter.start()
            self._meter = meter
            self.set_interval(1 / 10, self._poll)
        except AudioMeterError:
            pass  # no permission or framework missing — bars stay flat

    def on_unmount(self) -> None:
        if self._meter is not None:
            try:
                self._meter.stop()
            except Exception:
                pass
            self._meter = None

    def _poll(self) -> None:
        if self._meter is not None:
            new = self._meter.levels
            if new != self._levels:
                self._levels = new
                self.refresh()

    def render(self) -> Text:
        colors = _THEME_COLORS.get(self.app.theme, _DEFAULT_COLORS)
        left, right = self._levels
        t = _bar(left, colors)
        t.append(" ")
        t.append_text(_bar(right, colors))
        return t
