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


_HEADERS = {"User-Agent": "apple-music-tui/0.1 (https://github.com)"}

# Parenthetical suffixes Apple Music adds that lrclib typically doesn't have.
_STRIP_SUFFIXES_RE = re.compile(
    r"\s*\("
    r"(?:Remastered(?:\s+\d{4})?|Deluxe(?:\s+Edition)?|Bonus\s+Track\s+Version"
    r"|Anniversary\s+Edition|Expanded\s+Edition|Special\s+Edition)"
    r"\)\s*",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Strip common Apple Music parenthetical suffixes for better lrclib matching."""
    return _STRIP_SUFFIXES_RE.sub("", text).strip()


def _extract_lyrics(data: dict) -> dict:
    """Pull synced/plain lyrics from an lrclib response object."""
    return {
        "synced_lyrics": data.get("syncedLyrics") or None,
        "plain_lyrics": data.get("plainLyrics") or None,
    }


_EMPTY = {"synced_lyrics": None, "plain_lyrics": None}


def _get_exact(track: str, artist: str, album: str, duration: float) -> dict | None:
    """Try the /api/get exact-match endpoint. Returns None on miss."""
    params = urlencode({
        "track_name": track,
        "artist_name": artist,
        "album_name": album,
        "duration": int(duration),
    })
    url = f"https://lrclib.net/api/get?{params}"
    req = Request(url, headers=_HEADERS)
    try:
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        result = _extract_lyrics(data)
        if result["synced_lyrics"] or result["plain_lyrics"]:
            return result
    except (HTTPError, URLError, json.JSONDecodeError, OSError) as exc:
        _log.debug("lrclib.net exact lookup failed: %s", exc)
    return None


def _search_fallback(track: str, artist: str, duration: float) -> dict | None:
    """Try the /api/search endpoint for a fuzzy match. Returns None on miss."""
    params = urlencode({
        "track_name": track,
        "artist_name": artist,
    })
    url = f"https://lrclib.net/api/search?{params}"
    req = Request(url, headers=_HEADERS)
    try:
        with urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read().decode())
        if not results:
            return None
        # Prefer a result whose duration is close and that has synced lyrics
        int_dur = int(duration)
        best = None
        best_score = -1
        for entry in results:
            score = 0
            if entry.get("syncedLyrics"):
                score += 2
            elif entry.get("plainLyrics"):
                score += 1
            else:
                continue
            entry_dur = entry.get("duration") or 0
            if abs(entry_dur - int_dur) <= 3:
                score += 1
            if score > best_score:
                best = entry
                best_score = score
        if best:
            return _extract_lyrics(best)
    except (HTTPError, URLError, json.JSONDecodeError, OSError) as exc:
        _log.debug("lrclib.net search failed: %s", exc)
    return None


def fetch_lyrics(track: str, artist: str, album: str, duration: float) -> dict:
    """Fetch lyrics from lrclib.net (synchronous -- call via run_in_executor).

    Tries an exact match first, then falls back to a search query which
    tolerates slight metadata differences between Apple Music and lrclib.
    Strips common Apple Music suffixes like (Remastered) before retrying.
    """
    result = _get_exact(track, artist, album, duration)
    if result:
        return result

    # Retry exact match with normalized names (strips Remastered, Deluxe, etc.)
    clean_track = _normalize(track)
    clean_album = _normalize(album)
    if clean_track != track or clean_album != album:
        result = _get_exact(clean_track, artist, clean_album, duration)
        if result:
            _log.debug("lrclib.net: hit after normalizing %r -> %r", track, clean_track)
            return result

    result = _search_fallback(clean_track, artist, duration)
    if result:
        _log.debug("lrclib.net: exact miss, search hit for %r by %r", track, artist)
        return result

    return _EMPTY


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
