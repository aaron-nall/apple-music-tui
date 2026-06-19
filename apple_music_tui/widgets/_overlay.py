"""Shared behavior for centered, toggleable overlay widgets."""
from __future__ import annotations

from textual.events import Resize


class CenteredOverlay:
    """Mixin that centers an overlay on screen via offset.

    Hidden widgets (``display: none``) don't receive resize events, so the host
    must call :meth:`_center` when revealing the overlay.  Subclasses set the
    fractions to match their CSS ``width``/``height``.
    """

    OVERLAY_WIDTH_FRACTION: float = 0.8
    OVERLAY_HEIGHT_FRACTION: float = 0.8

    def on_resize(self, event: Resize) -> None:
        self._center()

    def _center(self) -> None:
        try:
            sw, sh = self.screen.size
            ow = int(sw * self.OVERLAY_WIDTH_FRACTION)
            oh = int(sh * self.OVERLAY_HEIGHT_FRACTION)
            self.styles.offset = ((sw - ow) // 2, (sh - oh) // 2)
        except Exception:
            pass
