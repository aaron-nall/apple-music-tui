from __future__ import annotations

import asyncio
from typing import Literal


class MusicClient:
    """Async interface to Apple Music via osascript."""

    _GET_STATE_SCRIPT = """\
tell application "Music"
    try
        set pState to player state as string
    on error
        return "stopped||0|0|0|||0|off|off"
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
    return pState & "|" & tName & "|" & tArtist & "|" & tAlbum & "|" & (pPos as string) & "|" & (tDur as string) & "|" & (sVol as string) & "|" & shufStr & "|" & rep
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
        except Exception:
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
            }
        parts = raw.split("|")
        if len(parts) < 9:
            parts.extend([""] * (9 - len(parts)))

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
        elif repeat_raw in ("all",):
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
