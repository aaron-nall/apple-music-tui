"""Full-screen audio-visualization overlay.

Hosts a small registry of visualizers; the shipped set is three stereo
frequency-spectrum (FFT) layouts driven by the app's shared ``AudioMeter``:

    0  Mirrored      — left channel rises above a center axis, right drops below
    1  Stacked       — left panel on top, right panel below
    2  Side-by-side  — left and right panels next to each other

Mechanics mirror ``LyricsOverlay``: hidden via ``display: none`` + a ``visible``
class, centered via the shared ``CenteredOverlay`` mixin.  Add a visualizer by
extending ``VIZ_NAMES`` / ``NUM_VIZ`` and the dispatch in ``render``.
"""
from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from apple_music_tui.widgets._meter_style import meter_colors
from apple_music_tui.widgets._overlay import CenteredOverlay

# Visualizer registry (index -> display name).
VIZ_NAMES = ("Mirrored", "Stacked", "Side-by-side")
NUM_VIZ = len(VIZ_NAMES)

# Per-band ballistics: fast rise, slow fall (classic spectrum-analyzer feel).
_ATTACK = 0.6
_RELEASE = 0.15

# Bar count is derived from width (1-cell bar + 1-cell gap), then clamped.
_MIN_BANDS = 4
_MAX_BANDS = 64        # full-width layouts (mirrored / stacked)
_MAX_BANDS_SPLIT = 48  # per-panel cap for side-by-side

# 1/8-block ramp for sub-cell vertical resolution; index 0 == empty, 8 == full.
_BLOCKS = " ▁▂▃▄▅▆▇█"


def _color_for(frac: float, colors: tuple[str, str, str]) -> str:
    """Pick low/mid/peak color by a bar's height fraction in [0, 1]."""
    low, mid, peak = colors
    if frac < 0.6:
        return low
    if frac < 0.85:
        return mid
    return peak


def _bars(values: list[float], height: int, colors: tuple[str, str, str],
          direction: str) -> list[Text]:
    """Render band *values* as vertical bars, one Text row per output line.

    ``direction`` is ``"up"`` (baseline at the bottom) or ``"down"`` (baseline
    at the top).  Rows are returned top-to-bottom; each row is
    ``2*len(values)-1`` cells wide (1-cell bar + 1-cell gap).
    """
    n = len(values)
    fills = [round(v * height * 8) for v in values]  # eighths filled per band
    rows: list[Text] = []
    for r in range(height):
        cells_from_base = (height - 1 - r) if direction == "up" else r
        units_below = cells_from_base * 8
        color = _color_for((cells_from_base + 1) / height, colors)
        line = Text()
        for bi in range(n):
            remaining = min(8, max(0, fills[bi] - units_below))
            line.append(_BLOCKS[remaining], style=None if remaining == 0 else color)
            if bi != n - 1:
                line.append(" ")
        rows.append(line)
    return rows


class VisualizationOverlay(CenteredOverlay, Widget):
    """Centered overlay rendering one of several stereo spectrum layouts."""

    DEFAULT_CSS = """
    VisualizationOverlay {
        display: none;
        layer: overlay;
        width: 80%;
        height: 80%;
        background: $surface;
        border: solid $accent;
        padding: 1 2;
    }
    VisualizationOverlay.visible {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._viz_index: int = 0
        self._sm_l: list[float] = []
        self._sm_r: list[float] = []

    def on_mount(self) -> None:
        self._center()
        # Poll at ~20 Hz; work is gated on visibility inside _poll.
        self.set_interval(1 / 20, self._poll)

    def show_viz(self, index: int) -> None:
        """Switch to visualizer *index* and reset smoothing state."""
        self._viz_index = index
        self._sm_l = []
        self._sm_r = []
        self.refresh()

    # ------------------------------------------------------------------
    # Polling / smoothing
    # ------------------------------------------------------------------

    def _bands_needed(self) -> int:
        w = max(self.size.width, 1)
        if self._viz_index == 2:  # side-by-side: two half-width panels
            panel_w = max(1, (w - 1) // 2)
            return max(_MIN_BANDS, min(_MAX_BANDS_SPLIT, (panel_w + 1) // 2))
        return max(_MIN_BANDS, min(_MAX_BANDS, (w + 1) // 2))

    def _smooth(self, target: list[float], smoothed: list[float]) -> list[float]:
        if len(smoothed) != len(target):
            return list(target)
        for i, v in enumerate(target):
            a = _ATTACK if v > smoothed[i] else _RELEASE
            smoothed[i] += a * (v - smoothed[i])
        return smoothed

    def _poll(self) -> None:
        if not self.has_class("visible"):
            return
        meter = getattr(self.app, "audio_meter", None)
        if meter is None:
            self.refresh()  # keep the "no audio" hint current
            return
        left, right = meter.spectrum(self._bands_needed())
        self._sm_l = self._smooth(left, self._sm_l)
        self._sm_r = self._smooth(right, self._sm_r)
        self.refresh()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _fit(values: list[float], n: int) -> list[float]:
        if len(values) == n:
            return values
        if len(values) > n:
            return values[:n]
        return values + [0.0] * (n - len(values))

    def render(self) -> Text:
        w, h = self.size.width, self.size.height
        if w < 4 or h < 3:
            return Text("")

        meter_missing = getattr(self.app, "audio_meter", None) is None
        header = Text(f"♪ Spectrum · {VIZ_NAMES[self._viz_index]}", style="bold")
        header.append(
            "  (no audio — grant Screen Recording)" if meter_missing else "  v: next   esc: close",
            style="dim",
        )

        colors = meter_colors(self.app.theme)
        n = self._bands_needed()
        left = self._fit(self._sm_l, n)
        right = self._fit(self._sm_r, n)
        body_h = h - 1  # header row

        if self._viz_index == 0:        # mirrored: right channel grows downward
            rows = self._render_split(left, right, body_h, colors, "down")
        elif self._viz_index == 1:      # stacked: both channels grow upward
            rows = self._render_split(left, right, body_h, colors, "up")
        else:
            rows = self._render_side_by_side(left, right, body_h, colors)

        return Text("\n").join([header, *rows])

    def _render_split(self, left, right, body_h, colors, bottom_dir) -> list[Text]:
        half = max(1, (body_h - 1) // 2)
        divider = Text("─" * (2 * len(left) - 1), style="dim")
        return [*_bars(left, half, colors, "up"), divider, *_bars(right, half, colors, bottom_dir)]

    def _render_side_by_side(self, left, right, body_h, colors) -> list[Text]:
        rows: list[Text] = []
        for lr, rr in zip(_bars(left, body_h, colors, "up"), _bars(right, body_h, colors, "up")):
            row = lr.copy()
            row.append(" │ ", style="dim")
            row.append_text(rr)
            rows.append(row)
        return rows
