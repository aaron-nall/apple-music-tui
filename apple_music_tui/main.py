import argparse
import asyncio
import logging
import sys

from apple_music_tui.app import AppleMusicApp
from apple_music_tui.library_cache import LibraryCache
from apple_music_tui.music_client import MusicClient

_log = logging.getLogger(__name__)


async def _run_update_cache() -> None:
    cache = LibraryCache()
    client = MusicClient()
    try:
        print("Fetching tracks from Apple Music library...")
        tracks = await client.get_all_tracks()
        if not tracks:
            print("  Warning: no tracks returned — is Apple Music running with a loaded library?", file=sys.stderr)
        else:
            print(f"  Fetched {len(tracks)} tracks")
            cache.replace_all(tracks)
            albums = cache.get_albums()
            print(f"  Cached {len(albums)} albums")

        print("Fetching playlists...")
        playlist_names = await client.get_playlists()
        print(f"  Found {len(playlist_names)} playlists")
        if playlist_names:
            track_lists = await asyncio.gather(
                *[client.get_playlist_tracks(name) for name in playlist_names]
            )
            playlists = dict(zip(playlist_names, track_lists))
            cache.replace_playlists(playlists)
            print(f"  Cached {len(playlists)} playlists")

        print("Cache update complete.")
    except Exception:
        _log.exception("Cache update failed")
        print("Error: cache update failed. Check logs for details.", file=sys.stderr)
        sys.exit(1)
    finally:
        cache.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="apple-music-tui")
    parser.add_argument(
        "--update-cache",
        action="store_true",
        help="Refresh the library cache without launching the TUI.",
    )
    args = parser.parse_args()

    if args.update_cache:
        logging.basicConfig(level=logging.WARNING)
        asyncio.run(_run_update_cache())
    else:
        app = AppleMusicApp()
        app.run()


if __name__ == "__main__":
    main()
