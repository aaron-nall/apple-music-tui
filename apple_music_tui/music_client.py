from __future__ import annotations

import asyncio
import logging
from typing import Literal

_log = logging.getLogger(__name__)


class MusicClient:
    """Async interface to Apple Music via osascript."""

    _DELIM = "|||"

    _GET_STATE_SCRIPT = """\
tell application "Music"
    set d to "|||"
    try
        set pState to player state as string
    on error
        return "stopped" & d & "" & d & "" & d & "" & d & "0" & d & "0" & d & "50" & d & "off" & d & "off"
    end try
    try
        set pPos to player position
    on error
        set pPos to 0
    end try
    try
        set tName to name of current track
        set tArtist to artist of current track
        set tAlbum to album of current track
        set tDur to duration of current track
    on error
        set tName to ""
        set tArtist to ""
        set tAlbum to ""
        set tDur to 0
    end try
    try
        set sVol to sound volume
    on error
        set sVol to 50
    end try
    try
        set shuf to shuffle enabled
        if shuf then
            set shufStr to "on"
        else
            set shufStr to "off"
        end if
    on error
        set shufStr to "off"
    end try
    try
        set rep to song repeat as string
    on error
        set rep to "off"
    end try
    try
        set plName to name of current playlist
    on error
        set plName to ""
    end try
    return pState & d & tName & d & tArtist & d & tAlbum & d & (pPos as string) & d & (tDur as string) & d & (sVol as string) & d & shufStr & d & rep & d & plName
end tell"""

    async def _run(self, script: str) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode != 0:
                return None
            return stdout.decode().strip()
        except (asyncio.TimeoutError, OSError, UnicodeDecodeError) as exc:
            _log.debug("osascript failed: %s", exc)
            return None

    async def get_state(self) -> dict:
        raw = await self._run(self._GET_STATE_SCRIPT)
        if not raw:
            return {
                "running": False,
                "state": "stopped",
                "track": "",
                "artist": "",
                "album": "",
                "position": 0.0,
                "duration": 0.0,
                "volume": 50,
                "shuffle": False,
                "repeat": "off",
                "current_playlist": "",
            }
        parts = raw.split(self._DELIM)
        if len(parts) < 10:
            parts.extend([""] * (10 - len(parts)))

        state_str = parts[0].strip().lower()
        # Map AppleScript state strings
        if "play" in state_str:
            state = "playing"
        elif "pause" in state_str:
            state = "paused"
        else:
            state = "stopped"

        def to_float(s: str) -> float:
            try:
                return float(s.strip().replace(",", "."))
            except (ValueError, AttributeError):
                return 0.0

        def to_int(s: str) -> int:
            try:
                return int(float(s.strip().replace(",", ".")))
            except (ValueError, AttributeError):
                return 0

        repeat_raw = parts[8].strip().lower()
        if repeat_raw == "one":
            repeat_mode = "one"
        elif repeat_raw == "all":
            repeat_mode = "all"
        else:
            repeat_mode = "off"

        return {
            "running": True,
            "state": state,
            "track": parts[1].strip(),
            "artist": parts[2].strip(),
            "album": parts[3].strip(),
            "position": to_float(parts[4]),
            "duration": to_float(parts[5]),
            "volume": to_int(parts[6]),
            "shuffle": parts[7].strip().lower() == "on",
            "repeat": repeat_mode,
            "current_playlist": parts[9].strip(),
        }

    async def play_pause(self) -> None:
        await self._run('tell application "Music" to playpause')

    async def next_track(self) -> None:
        await self._run('tell application "Music" to next track')

    async def previous_track(self) -> None:
        await self._run('tell application "Music" to previous track')

    async def set_shuffle(self, enabled: bool) -> None:
        val = "true" if enabled else "false"
        await self._run(f'tell application "Music" to set shuffle enabled to {val}')

    async def set_repeat(self, mode: Literal["off", "one", "all"]) -> None:
        await self._run(f'tell application "Music" to set song repeat to {mode}')

    async def set_position(self, seconds: float) -> None:
        await self._run(f'tell application "Music" to set player position to {seconds}')

    async def set_volume(self, level: int) -> None:
        level = max(0, min(100, level))
        await self._run(f'tell application "Music" to set sound volume to {level}')

    async def get_playlists(self) -> list[str]:
        script = """\
tell application "Music"
    set d to "|||"
    set output to ""
    repeat with pl in (every playlist whose special kind is none)
        set output to output & (name of pl as string) & d
    end repeat
    return output
end tell"""
        raw = await self._run(script)
        if not raw:
            return []
        return [p.strip() for p in raw.split(self._DELIM) if p.strip()]

    async def play_playlist(self, name: str) -> None:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        script = f"""\
tell application "Music"
    set matchedPL to first playlist whose name is "{escaped}"
    play matchedPL
end tell"""
        await self._run(script)

    async def get_playlist_tracks(self, name: str) -> list[str]:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        script = f"""\
tell application "Music"
    set d to "|||"
    set output to ""
    set matchedPL to first playlist whose name is "{escaped}"
    repeat with t in (every track of matchedPL)
        set output to output & (name of t as string) & d
    end repeat
    return output
end tell"""
        raw = await self._run(script)
        if not raw:
            return []
        return [t.strip() for t in raw.split(self._DELIM) if t.strip()]

    async def play_playlist_track(self, playlist_name: str, track_index: int) -> None:
        escaped = playlist_name.replace("\\", "\\\\").replace('"', '\\"')
        script = f"""\
tell application "Music"
    set matchedPL to first playlist whose name is "{escaped}"
    play (track {track_index} of matchedPL)
end tell"""
        await self._run(script)
