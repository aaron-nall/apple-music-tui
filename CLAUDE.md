# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install

# Run the app
poetry run apple-music-tui

# Run tests
poetry run pytest
poetry run pytest tests/test_music_client.py  # single file
poetry run pytest -v                          # verbose
```

## Architecture

Python 3.11+ TUI application built on [Textual](https://github.com/Textualize/textual). Controls Apple Music on macOS via osascript/AppleScript. No Apple Music API — all communication goes through `osascript` subprocess calls.

### Core modules

- **`app.py`** — `AppleMusicApp(App)`: root of the Textual app. Owns the 1-second polling loop (`_poll_state`), keyboard bindings, album continuation logic, and synchronized lyrics orchestration.
- **`music_client.py`** — `MusicClient`: async wrapper around osascript. Every player action (play/pause, next/prev, seek, volume, playlist control) goes through here.
- **`library_cache.py`** — `LibraryCache`: SQLite cache (30-day TTL) for albums, tracks, playlists, and fetched lyrics. Reduces repeated osascript calls for static library data.
- **`lyrics.py`** — Fetches time-synced lyrics from lrclib.net, parses LRC format, and detects "gaps" (long silences between lyric lines).
- **`config.py`** — `AppConfig` (Pydantic Settings): persists user preferences (theme) to `~/.config/apple-music-tui/config.json`.
- **`themes.py`** — Custom Textual themes: `amber-terminal` and `green-terminal` (CRT phosphor styles).

### Widgets (`widgets/`)

Each widget is a self-contained Textual component mounted by `app.py`:

| Widget | Role |
|---|---|
| `now_playing.py` | Scrolling marquee for track/artist/album |
| `controls.py` | Play/pause, shuffle/repeat toggles, clickable volume bar |
| `playlist_browser.py` | Tabbed browser for playlists and albums with expandable rows |
| `lyrics_overlay.py` | Full-screen overlay with synchronized lyrics; click a line to seek |
| `airplay_picker.py` | AirPlay device selection overlay |
| `status_bar.py` | Status display bar |

### Key patterns

- **State polling**: `app.py` polls Apple Music every second. Widget updates flow from this poll — don't implement separate polling inside widgets.
- **Reactive properties**: Textual's `reactive` is used for data binding between app state and widget display.
- **Album continuation**: `app.py` implements logic to auto-advance through album tracks when the current track ends — this lives entirely in the poll loop.
- **Lyrics sync**: after fetching from lrclib.net (with library cache), lyrics lines are matched to the current playback position in the poll loop; gap lines are animated.
- **osascript calls are async**: all `MusicClient` methods are `async def` and should be awaited; they shell out to `osascript` under the hood.
