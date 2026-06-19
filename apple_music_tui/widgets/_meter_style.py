"""Shared color palette for audio-meter widgets (VU meter + spectrum visualizer)."""
from __future__ import annotations

# Per-theme (low, mid, peak) colors for meter bars.
THEME_COLORS: dict[str, tuple[str, str, str]] = {
    "amber-terminal": ("#7A4F00", "#CC8800", "#FFCC33"),
    "green-terminal": ("#006600", "#00CC00", "#66FF66"),
}
DEFAULT_COLORS: tuple[str, str, str] = ("green", "yellow", "red")


def meter_colors(theme: str) -> tuple[str, str, str]:
    """Return the ``(low, mid, peak)`` colors for *theme*."""
    return THEME_COLORS.get(theme, DEFAULT_COLORS)
