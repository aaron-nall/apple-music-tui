"""Shared color palette for audio-meter widgets (VU meter + spectrum visualizer)."""
from __future__ import annotations

from functools import lru_cache

from textual.app import App
from textual.color import Color


@lru_cache(maxsize=None)
def _palette(primary: str, secondary: str | None, accent: str | None) -> tuple[str, str, str]:
    base = Color.parse(primary)
    low = secondary or base.darken(0.35).hex
    peak = accent or base.lighten(0.35).hex
    return (low, primary, peak)


def meter_colors(app: App) -> tuple[str, str, str]:
    """Return the ``(low, mid, peak)`` bar colors for the app's active theme.

    Colors are pulled from the theme's ``secondary``/``primary``/``accent``
    palette so the meters mesh with whatever theme is selected. Themes that
    leave ``secondary`` or ``accent`` unset fall back to luminance-shifted
    variants of ``primary``. Results are memoized per palette since the meter
    re-renders many times per second but the theme rarely changes.
    """
    theme = app.current_theme
    return _palette(theme.primary, theme.secondary, theme.accent)
