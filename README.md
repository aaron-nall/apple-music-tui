# Apple Music TUI

A terminal UI for controlling Apple Music on macOS via osascript.

## Requirements

- macOS with Apple Music app
- Python 3.11+
- Poetry

## Install

```bash
poetry install
```

## Run

```bash
poetry run apple-music-tui
```

## Controls

| Key            | Action                        |
|----------------|-------------------------------|
| `space`        | Play / Pause                  |
| `→` / `l`      | Next track                    |
| `←` / `h`      | Previous track                |
| `s`            | Toggle shuffle                |
| `r`            | Cycle repeat                  |
| `t`            | Cycle theme                   |
| `+` / `=`      | Volume up 5                   |
| `-`            | Volume down 5                 |
| `tab`          | Toggle Playlists / Albums     |
| `a`            | Toggle album sort order       |
| `o`            | Open AirPlay device picker    |
| `y`            | Toggle lyrics overlay         |
| `escape`       | Close overlay                 |
| `?`            | Show help                     |
| `q`            | Quit                          |

All control buttons are also clickable. Click the progress bar to seek.

## Features

- **Library browser** — browse playlists and albums; expand to see tracks and click to play
- **Now playing** — scrolling marquee for long track/album/artist names
- **AirPlay picker** — select output device without leaving the terminal
- **Synchronized lyrics** — fetched from [lrclib.net](https://lrclib.net), highlighted line follows playback with click-to-seek; gap sections animate with a `* * *` indicator
- **Themes** — cycle through multiple color themes including CRT variants
- **Lyrics cache** — lyrics stored locally with a 30-day TTL
