# Apple Music TUI

A minimal terminal UI for controlling Apple Music on macOS via osascript.

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

| Key       | Action           |
|-----------|------------------|
| `space`   | Play / Pause     |
| `→` / `l` | Next track       |
| `←` / `h` | Previous track   |
| `s`       | Toggle shuffle   |
| `r`       | Cycle repeat     |
| `+` / `=` | Volume up 5      |
| `-`       | Volume down 5    |
| `q`       | Quit             |

All control buttons are also clickable. Click the progress bar to seek.
