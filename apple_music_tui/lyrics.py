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

GAP_SENTINEL = "\x00"  # Marks a gap pseudo-line in parsed lyrics


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


def insert_gap_lines(
    lyrics: list[tuple[float, str]], min_gap: float = 5.0
) -> list[tuple[float, str]]:
    """Insert a gap pseudo-line between consecutive lyrics separated by > min_gap seconds.

    The gap line is placed at the midpoint of the gap so the preceding lyric
    keeps its highlight for a natural amount of time before the gap indicator
    takes over.
    """
    if len(lyrics) < 2:
        return lyrics
    result: list[tuple[float, str]] = []
    for i, (ts, text) in enumerate(lyrics):
        result.append((ts, text))
        if i + 1 < len(lyrics):
            next_ts = lyrics[i + 1][0]
            if next_ts - ts > min_gap:
                result.append(((ts + next_ts) / 2, GAP_SENTINEL))
    return result


def find_current_line(lyrics: list[tuple[float, str]], position: float) -> int:
    """Return the index of the current lyric line for the given playback position."""
    if not lyrics:
        return -1
    timestamps = [t for t, _ in lyrics]
    idx = bisect_right(timestamps, position)
    return idx - 1
