from __future__ import annotations

import asyncio
import logging
from typing import Literal, TypedDict

_log = logging.getLogger(__name__)


class AirPlayDevice(TypedDict):
    name: str
    kind: str
    selected: bool
    index: int  # 1-based AppleScript index for disambiguation


class MusicState(TypedDict):
    running: bool
    state: str
    track: str
    artist: str
    album: str
    position: float
    duration: float
    volume: int
    shuffle: bool
    repeat: str
    current_playlist: str


class MusicClient:
    """Async interface to Apple Music via osascript."""

    _DELIM = "|||"

    # Outputs one "KEY: value" pair per line so parsing is position-independent.
    # Adding or reordering fields in the future won't silently corrupt state.
    _GET_STATE_SCRIPT = """\
tell application "Music"
    try
        set pState to player state as string
    on error
        return "STATE: stopped" & return & "TRACK: " & return & "ARTIST: " & return & "ALBUM: " & return & "POSITION: 0" & return & "DURATION: 0" & return & "VOLUME: 50" & return & "SHUFFLE: off" & return & "REPEAT: off" & return & "PLAYLIST: "
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
    try
        set tIdx to index of current track
    on error
        set tIdx to 0
    end try
    return "STATE: " & pState & return & "TRACK: " & tName & return & "ARTIST: " & tArtist & return & "ALBUM: " & tAlbum & return & "POSITION: " & (pPos as string) & return & "DURATION: " & (tDur as string) & return & "VOLUME: " & (sVol as string) & return & "SHUFFLE: " & shufStr & return & "REPEAT: " & rep & return & "PLAYLIST: " & plName & return & "TRACKIDX: " & (tIdx as string)
end tell"""

    async def _run(self, script: str, timeout: float = 5.0) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                if stderr:
                    _log.debug("osascript error: %s", stderr.decode(errors="replace").strip())
                return None
            return stdout.decode().strip()
        except (asyncio.TimeoutError, OSError, UnicodeDecodeError) as exc:
            _log.debug("osascript failed: %s", exc)
            return None

    async def get_state(self) -> MusicState:
        _defaults: MusicState = {
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
        raw = await self._run(self._GET_STATE_SCRIPT)
        if not raw:
            return _defaults

        # Parse "KEY: value" lines — order-independent, tolerant of new fields.
        # partition(": ") splits only on the first occurrence, so values that
        # contain ": " (e.g. "Act 1: The Beginning") are preserved intact.
        data: dict[str, str] = {}
        for line in raw.splitlines():
            key, sep, value = line.partition(": ")
            if sep:
                data[key.strip()] = value

        if not data:
            _log.debug("get_state: failed to parse output: %r", raw)
            return _defaults

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

        state_str = data.get("STATE", "stopped").lower()
        if "play" in state_str:
            state = "playing"
        elif "pause" in state_str:
            state = "paused"
        else:
            state = "stopped"

        repeat_raw = data.get("REPEAT", "off").strip().lower()
        if repeat_raw == "one":
            repeat_mode = "one"
        elif repeat_raw == "all":
            repeat_mode = "all"
        else:
            repeat_mode = "off"

        return {
            "running": True,
            "state": state,
            "track": data.get("TRACK", ""),
            "artist": data.get("ARTIST", ""),
            "album": data.get("ALBUM", ""),
            "position": to_float(data.get("POSITION", "0")),
            "duration": to_float(data.get("DURATION", "0")),
            "volume": to_int(data.get("VOLUME", "50")),
            "shuffle": data.get("SHUFFLE", "off").strip().lower() == "on",
            "repeat": repeat_mode,
            "current_playlist": data.get("PLAYLIST", ""),
            "track_index": to_int(data.get("TRACKIDX", "0")),
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
        return [p.strip() for p in raw.split(self._DELIM) if p.strip() and p.strip() != "Music Videos" ]

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
        skips = track_index - 1
        script = f"""\
tell application "Music"
    set matchedPL to first playlist whose name is "{escaped}"
    play matchedPL
    delay 0.3
    pause
    repeat {skips} times
        delay 0.1
        next track
    end repeat
    play
end tell"""
        await self._run(script)

    async def get_albums(self) -> list[tuple[str, str]]:
        """Return deduplicated (album_name, artist) tuples sorted alphabetically."""
        script = """\
tell application "Music"
    set d to "|||"
    set r to ">>>"
    set AppleScript's text item delimiters to d
    set albumList to (album of every track of library playlist 1) as string
    set artistList to (album artist of every track of library playlist 1) as string
    return albumList & r & artistList
end tell"""
        raw = await self._run(script)
        if not raw:
            return []
        parts = raw.split(">>>")
        if len(parts) != 2:
            return []
        albums = [a.strip() for a in parts[0].split(self._DELIM)]
        artists = [a.strip() for a in parts[1].split(self._DELIM)]
        seen: set[tuple[str, str]] = set()
        result: list[tuple[str, str]] = []
        for album, artist in zip(albums, artists):
            if not album:
                continue
            key = (album, artist)
            if key not in seen:
                seen.add(key)
                result.append(key)
        result.sort(key=lambda x: x[0].lower())
        return result

    async def get_album_tracks(self, album_name: str, artist: str = "") -> list[str]:
        escaped = album_name.replace("\\", "\\\\").replace('"', '\\"')
        condition = f'whose album is "{escaped}"'
        if artist:
            escaped_artist = artist.replace("\\", "\\\\").replace('"', '\\"')
            condition += f' and album artist is "{escaped_artist}"'
        script = f"""\
tell application "Music"
    set d to "|||"
    set output to ""
    repeat with t in (every track of library playlist 1 {condition})
        set output to output & (name of t as string) & d
    end repeat
    return output
end tell"""
        raw = await self._run(script)
        if not raw:
            return []
        return [t.strip() for t in raw.split(self._DELIM) if t.strip()]

    async def play_album(self, album_name: str, artist: str = "") -> None:
        escaped = album_name.replace("\\", "\\\\").replace('"', '\\"')
        condition = f'whose album is "{escaped}"'
        if artist:
            escaped_artist = artist.replace("\\", "\\\\").replace('"', '\\"')
            condition += f' and album artist is "{escaped_artist}"'
        script = f"""\
tell application "Music"
    play (first track of library playlist 1 {condition})
end tell"""
        await self._run(script)

    async def play_album_track(self, album_name: str, track_index: int, track_name: str = "", artist: str = "") -> None:
        escaped_album = album_name.replace("\\", "\\\\").replace('"', '\\"')
        artist_clause = ""
        if artist:
            escaped_artist = artist.replace("\\", "\\\\").replace('"', '\\"')
            artist_clause = f' and album artist is "{escaped_artist}"'
        if track_name:
            escaped_track = track_name.replace("\\", "\\\\").replace('"', '\\"')
            script = f"""\
tell application "Music"
    play (first track of library playlist 1 whose album is "{escaped_album}" and name is "{escaped_track}"{artist_clause})
end tell"""
        else:
            script = f"""\
tell application "Music"
    set albumTracks to (every track of library playlist 1 whose album is "{escaped_album}"{artist_clause})
    play item {track_index} of albumTracks
end tell"""
        await self._run(script)

    async def get_all_tracks(self) -> list[dict]:
        """Bulk-fetch all library track metadata for cache population."""
        script = """\
tell application "Music"
    set d to "|||"
    set r to ">>>"
    set AppleScript's text item delimiters to d
    set nameList to (name of every track of library playlist 1) as string
    set albumList to (album of every track of library playlist 1) as string
    set artistList to (album artist of every track of library playlist 1) as string
    set numList to (track number of every track of library playlist 1) as string
    return nameList & r & albumList & r & artistList & r & numList
end tell"""
        raw = await self._run(script, timeout=60.0)
        if not raw:
            return []
        parts = raw.split(">>>")
        if len(parts) != 4:
            return []
        names = parts[0].split(self._DELIM)
        albums = parts[1].split(self._DELIM)
        artists = parts[2].split(self._DELIM)
        numbers = parts[3].split(self._DELIM)
        result: list[dict] = []
        for name, album, artist, num in zip(names, albums, artists, numbers):
            name = name.strip()
            album = album.strip()
            if not name or not album:
                continue
            try:
                track_num = int(float(num.strip().replace(",", ".")))
            except (ValueError, AttributeError):
                track_num = 0
            result.append({
                "track_name": name,
                "album": album,
                "artist": artist.strip(),
                "track_number": track_num,
            })
        return result

    async def get_airplay_devices(self) -> list[AirPlayDevice]:
        script = """\
tell application "Music"
    set d to "|||"
    set r to ">>>"
    set AppleScript's text item delimiters to d
    set nameStr to (name of every AirPlay device) as string
    set kindStr to (kind of every AirPlay device) as string
    set selStr to (selected of every AirPlay device) as string
    return nameStr & r & kindStr & r & selStr
end tell"""
        raw = await self._run(script)
        if not raw:
            return []
        parts = raw.split(">>>")
        if len(parts) != 3:
            return []
        names = [n.strip() for n in parts[0].split(self._DELIM)]
        kinds = [k.strip() for k in parts[1].split(self._DELIM)]
        sels = [s.strip().lower() == "true" for s in parts[2].split(self._DELIM)]
        result: list[AirPlayDevice] = []
        for i, (name, kind, selected) in enumerate(zip(names, kinds, sels)):
            if not name:
                continue
            result.append({"name": name, "kind": kind, "selected": selected, "index": i + 1})
        return result

    async def set_airplay_device_selected(self, index: int, selected: bool) -> None:
        val = "true" if selected else "false"
        await self._run(f'tell application "Music" to set selected of AirPlay device {index} to {val}')
