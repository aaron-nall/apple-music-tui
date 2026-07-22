"""Tests for lyrics fetching, LRC parsing, and gap detection."""
from __future__ import annotations

from urllib.error import HTTPError, URLError

import pytest

from apple_music_tui import lyrics as lyrics_mod
from apple_music_tui.lyrics import (
    GAP_SENTINEL,
    TransientLyricsError,
    _normalize,
    fetch_lyrics,
    find_current_line,
    insert_gap_lines,
    parse_lrc,
)


class TestParseLrc:
    def test_two_digit_centiseconds(self) -> None:
        assert parse_lrc("[00:12.34] Hello") == [(12.34, "Hello")]

    def test_three_digit_milliseconds(self) -> None:
        assert parse_lrc("[01:02.345] World") == [(62.345, "World")]

    def test_out_of_order_lines_are_sorted(self) -> None:
        text = "[00:30.00] Second\n[00:10.00] First"
        assert parse_lrc(text) == [(10.0, "First"), (30.0, "Second")]

    def test_malformed_lines_are_skipped(self) -> None:
        text = "not a timestamp\n[00:05.00] Real line\n[bad] nope\n[1:2.3] also bad"
        assert parse_lrc(text) == [(5.0, "Real line")]

    def test_empty_text_line_preserved(self) -> None:
        assert parse_lrc("[00:05.00]") == [(5.0, "")]


class TestInsertGapLines:
    def test_gap_inserted_at_midpoint(self) -> None:
        lyrics = [(0.0, "a"), (10.0, "b")]
        result = insert_gap_lines(lyrics, min_gap=5.0)
        assert result == [(0.0, "a"), (5.0, GAP_SENTINEL), (10.0, "b")]

    def test_no_gap_under_threshold(self) -> None:
        lyrics = [(0.0, "a"), (4.0, "b")]
        assert insert_gap_lines(lyrics, min_gap=5.0) == lyrics

    def test_fewer_than_two_lines_passthrough(self) -> None:
        assert insert_gap_lines([]) == []
        assert insert_gap_lines([(1.0, "solo")]) == [(1.0, "solo")]


class TestFindCurrentLine:
    LYRICS = [(10.0, "a"), (20.0, "b"), (30.0, "c")]

    def test_empty_lyrics(self) -> None:
        assert find_current_line([], 5.0) == -1

    def test_before_first_line(self) -> None:
        assert find_current_line(self.LYRICS, 5.0) == -1

    def test_exact_hit(self) -> None:
        assert find_current_line(self.LYRICS, 20.0) == 1

    def test_between_lines(self) -> None:
        assert find_current_line(self.LYRICS, 25.0) == 1

    def test_past_end(self) -> None:
        assert find_current_line(self.LYRICS, 99.0) == 2


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Album (Remastered)", "Album"),
            ("Album (Remaster)", "Album"),
            ("Album (Remastered 2009)", "Album"),
            ("Album (Deluxe Edition)", "Album"),
            ("Album (Bonus Track Version)", "Album"),
            ("Plain Album", "Plain Album"),
        ],
    )
    def test_suffix_stripping(self, raw: str, expected: str) -> None:
        assert _normalize(raw) == expected


class TestFetchLyrics:
    """Exercise the exact -> normalized -> search fallback chain with a fake HTTP layer."""

    def test_exact_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake(url: str, timeout: float):
            assert "/api/get?" in url
            return {"syncedLyrics": "[00:01.00] hi", "plainLyrics": "hi"}

        monkeypatch.setattr(lyrics_mod, "_request_json", fake)
        result = fetch_lyrics("Song", "Artist", "Album", 180)
        assert result["synced_lyrics"] == "[00:01.00] hi"

    def test_normalized_retry_after_exact_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake(url: str, timeout: float):
            calls.append(url)
            if "Remastered" in url:
                return None
            if "/api/get?" in url:
                return {"syncedLyrics": None, "plainLyrics": "found"}
            return None

        monkeypatch.setattr(lyrics_mod, "_request_json", fake)
        result = fetch_lyrics("Song", "Artist", "Album (Remastered)", 180)
        assert result["plain_lyrics"] == "found"
        assert len(calls) == 2

    def test_search_fallback_prefers_synced_and_close_duration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake(url: str, timeout: float):
            if "/api/get?" in url:
                return None
            return [
                {"plainLyrics": "plain only", "duration": 180},
                {"syncedLyrics": "far duration", "duration": 500},
                {"syncedLyrics": "best match", "duration": 181},
            ]

        monkeypatch.setattr(lyrics_mod, "_request_json", fake)
        result = fetch_lyrics("Song", "Artist", "Album", 180)
        assert result["synced_lyrics"] == "best match"

    def test_total_miss_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lyrics_mod, "_request_json", lambda url, timeout: None)
        result = fetch_lyrics("Song", "Artist", "Album", 180)
        assert result == {"synced_lyrics": None, "plain_lyrics": None}

    def test_transient_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(url: str, timeout: float):
            raise TransientLyricsError("lrclib down")

        monkeypatch.setattr(lyrics_mod, "_request_json", boom)
        with pytest.raises(TransientLyricsError):
            fetch_lyrics("Song", "Artist", "Album", 180)


class TestRequestJson:
    """A definitive miss (4xx) must be distinguishable from a transient outage."""

    def test_4xx_is_definitive_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_404(req, timeout):
            raise HTTPError("https://lrclib.net", 404, "Not Found", {}, None)

        monkeypatch.setattr(lyrics_mod, "urlopen", raise_404)
        assert lyrics_mod._request_json("https://lrclib.net/api/get?x", 1.0) is None

    def test_5xx_retries_then_raises_transient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []

        def raise_502(req, timeout):
            calls.append(1)
            raise HTTPError("https://lrclib.net", 502, "Bad Gateway", {}, None)

        monkeypatch.setattr(lyrics_mod, "urlopen", raise_502)
        monkeypatch.setattr(lyrics_mod.time, "sleep", lambda _s: None)
        with pytest.raises(TransientLyricsError):
            lyrics_mod._request_json("https://lrclib.net/api/get?x", 1.0)
        assert len(calls) == lyrics_mod._MAX_ATTEMPTS

    def test_network_error_retries_then_raises_transient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_urlerror(req, timeout):
            raise URLError("connection refused")

        monkeypatch.setattr(lyrics_mod, "urlopen", raise_urlerror)
        monkeypatch.setattr(lyrics_mod.time, "sleep", lambda _s: None)
        with pytest.raises(TransientLyricsError):
            lyrics_mod._request_json("https://lrclib.net/api/get?x", 1.0)
