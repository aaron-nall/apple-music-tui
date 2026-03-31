"""Lyrics fetching from lrclib.net and LRC format parsing."""
from __future__ import annotations

import json
import logging
import re
from bisect import bisect_right
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_log = logging.getLogger(__name__)

_LRC_RE = re.compile(r"^\[(\d{2}):(\d{2})\.(\d{2,3})\]\s?(.*)$")


def fetch_lyrics(track: str, artist: str, album: str, duration: float) -> dict:
    """Fetch lyrics from lrclib.net (synchronous -- call via run_in_executor)."""
    params = urlencode({
        "track_name": track,
        "artist_name": artist,
        "album_name": album,
        "duration": int(duration),
    })
    url = f"https://lrclib.net/api/get?{params}"
    req = Request(url, headers={"User-Agent": "apple-music-tui/0.1 (https://github.com)"})
    try:
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return {
            "synced_lyrics": data.get("syncedLyrics") or None,
            "plain_lyrics": data.get("plainLyrics") or None,
        }
    except (HTTPError, URLError, json.JSONDecodeError, OSError) as exc:
        _log.debug("lrclib.net request failed: %s", exc)
        return {"synced_lyrics": None, "plain_lyrics": None}


def parse_lrc(lrc_text: str) -> list[tuple[float, str]]:
    """Parse LRC synced lyrics into [(seconds, line_text), ...] sorted by time."""
    lines: list[tuple[float, str]] = []
    for raw in lrc_text.splitlines():
        m = _LRC_RE.match(raw)
        if m:
            mins, secs, frac, text = m.groups()
            # Handle both 2-digit centiseconds and 3-digit milliseconds
            if len(frac) == 2:
                frac_sec = int(frac) / 100
            else:
                frac_sec = int(frac) / 1000
            timestamp = int(mins) * 60 + int(secs) + frac_sec
            lines.append((timestamp, text))
    lines.sort(key=lambda x: x[0])
    return lines


def find_current_line(lyrics: list[tuple[float, str]], position: float) -> int:
    """Return the index of the current lyric line for the given playback position."""
    if not lyrics:
        return -1
    timestamps = [t for t, _ in lyrics]
    idx = bisect_right(timestamps, position)
    return idx - 1
