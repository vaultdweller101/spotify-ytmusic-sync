import argparse
import os
import sys
import io

# Force UTF-8 encoding on standard output and error to support international characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from src.matcher import Track
from src.spotify_client import SpotifyClient, extract_spotify_playlist_id
from src.ytmusic_client import YTMusicClient, extract_ytmusic_playlist_id
from src.syncer import PlaylistSyncer


def print_banner():
    banner = r"""
===========================================================
      Spotify <--> YouTube Music Bi-Directional Syncer     
===========================================================
"""
    print(banner)


def cmd_test(args):
    """Tests authentication to both Spotify and YouTube Music."""
    print("Testing connections...\n")

    # 1. Test Spotify
    print("[1/2] Checking Spotify connection...")
    try:
        sp_client = SpotifyClient()
        user_info = sp_client.test_connection()
        print(f"  [OK] Connected to Spotify as: {user_info.get('display_name')} (ID: {user_info.get('id')})")
    except Exception as e:
        print(f"  [FAIL] Spotify connection failed: {e}")
        print("  -> Tip: Run 'python sync.py setup-spotify' to configure Spotify credentials.")

    print()

    # 2. Test YouTube Music
    print("[2/2] Checking YouTube Music connection...")
    try:
        yt_client = YTMusicClient(auth_file=args.yt_auth if hasattr(args, "yt_auth") else None)
        status = yt_client.test_connection()
        print(f"  [OK] Connected to YouTube Music! Using: {status.get('auth_file')}")
    except Exception as e:
        print(f"  [FAIL] YouTube Music connection failed: {e}")
        print("  -> Tip: Run 'python sync.py setup-ytmusic' to configure YouTube Music credentials.")


def cmd_setup_spotify(args):
    """Interactive wizard to configure Spotify credentials."""
    print("\n--- Spotify Setup Guide ---")
    print("1. Go to https://developer.spotify.com/dashboard and log in.")
    print("2. Click 'Create App'.")
    print("3. App Name: 'Music Syncer' (or any name you prefer).")
    print("4. Redirect URI: Add 'http://localhost:8888/callback'")
    print("5. Which API are you planning on using? Select 'Web API'.")
    print("6. Save your app, then go to Settings to find your Client ID & Client Secret.\n")

    client_id = input("Enter Spotify Client ID: ").strip()
    client_secret = input("Enter Spotify Client Secret: ").strip()
    redirect_uri = input("Enter Redirect URI (press Enter for http://localhost:8888/callback): ").strip()
    if not redirect_uri:
        redirect_uri = "http://localhost:8888/callback"

    if not client_id or not client_secret:
        print("Error: Client ID and Client Secret cannot be empty.")
        return

    # Update or create .env file
    env_lines = []
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if not any(line.startswith(k) for k in ["SPOTIPY_CLIENT_ID=", "SPOTIPY_CLIENT_SECRET=", "SPOTIPY_REDIRECT_URI="]):
                    env_lines.append(line)

    env_lines.append(f"SPOTIPY_CLIENT_ID={client_id}\n")
    env_lines.append(f"SPOTIPY_CLIENT_SECRET={client_secret}\n")
    env_lines.append(f"SPOTIPY_REDIRECT_URI={redirect_uri}\n")

    with open(".env", "w", encoding="utf-8") as f:
        f.writelines(env_lines)

    os.environ["SPOTIPY_CLIENT_ID"] = client_id
    os.environ["SPOTIPY_CLIENT_SECRET"] = client_secret
    os.environ["SPOTIPY_REDIRECT_URI"] = redirect_uri

    print("\nSaved Spotify credentials to .env.")
    print("Now opening browser for initial Spotify authentication...")
    try:
        sp_client = SpotifyClient()
        user_info = sp_client.test_connection()
        print(f"\n[Success!] Spotify authentication successful for: {user_info.get('display_name')}")
    except Exception as e:
        print(f"\n[Warning] Authorization prompt error: {e}")


def cmd_setup_ytmusic(args):
    """Guides user to set up YouTube Music auth."""
    print("\n--- YouTube Music Setup ---")
    print("YouTube Music requires authentication to read and edit your personal playlists.")
    print("There are two ways to authenticate:\n")
    print("Option 1: Browser Headers (Recommended & Quickest)")
    print("  1. Open Chrome/Firefox/Edge and go to https://music.youtube.com")
    print("  2. Ensure you are signed in.")
    print("  3. Press F12 to open Developer Tools -> Go to 'Network' tab.")
    print("  4. Filter by '/browse' or click on any playlist or song in YouTube Music.")
    print("  5. Right-click any POST or GET request to music.youtube.com -> Copy -> Copy request headers (or copy as cURL).")
    print("  6. Run:")
    print("       ytmusicapi browser")
    print("     and paste your copied headers into the prompt.\n")
    print("Option 2: OAuth Credentials")
    print("  Run:")
    print("       ytmusicapi oauth")
    print("  Follow the on-screen instructions to authorize Google YouTube Music API.\n")

    choice = input("Would you like to run the interactive browser setup now? (y/n): ").strip().lower()
    if choice == "y":
        try:
            import ytmusicapi
            print("\nPlease paste your request headers below (press Ctrl+Z or Enter twice when done depending on your terminal):")
            ytmusicapi.setup(filepath="browser.json")
            print("\n[Success!] browser.json has been generated successfully.")
        except Exception as e:
            print(f"Setup exited: {e}")


def cmd_sync(args):
    """Executes the two-way sync."""
    sp_playlist = args.spotify or os.getenv("SPOTIFY_PLAYLIST_ID")
    yt_playlist = args.ytmusic or os.getenv("YTMUSIC_PLAYLIST_ID")

    if not sp_playlist:
        sp_playlist = input("Enter Spotify Playlist URL or ID: ").strip()
    if not yt_playlist:
        yt_playlist = input("Enter YouTube Music Playlist URL or ID: ").strip()

    if not sp_playlist or not yt_playlist:
        print("Error: Both Spotify and YouTube Music playlist identifiers are required.")
        sys.exit(1)

    # Initialize clients
    try:
        sp_client = SpotifyClient()
    except Exception as e:
        print(f"Error initializing Spotify client: {e}")
        print("Run 'python sync.py setup-spotify' to configure your Spotify credentials.")
        sys.exit(1)

    try:
        yt_client = YTMusicClient(auth_file=args.yt_auth)
    except Exception as e:
        print(f"Error initializing YouTube Music client: {e}")
        sys.exit(1)

    syncer = PlaylistSyncer(
        spotify_client=sp_client,
        ytmusic_client=yt_client,
        cache_path=args.cache,
        min_match_score=args.min_score,
    )

    report = syncer.sync(
        spotify_playlist_id=sp_playlist,
        ytmusic_playlist_id=yt_playlist,
        dry_run=args.dry_run,
        direction=getattr(args, "direction", "both"),
    )

    # Print summary
    print("\n" + "=" * 55)
    print("                 SYNC SUMMARY")
    print("=" * 55)
    print(f"Initial tracks on Spotify:        {report.spotify_total}")
    print(f"Initial tracks on YouTube Music:  {report.ytmusic_total}")
    print(f"Tracks already synchronized:      {report.already_synced_count}")
    print(f"Tracks added to YouTube Music:    {len(report.added_to_ytmusic)}")
    print(f"Tracks added to Spotify:          {len(report.added_to_spotify)}")

    if report.unmatched_for_ytmusic:
        print(f"\nTracks not found on YouTube Music ({len(report.unmatched_for_ytmusic)}):")
        for t in report.unmatched_for_ytmusic:
            print(f"  - {t}")

    if report.unmatched_for_spotify:
        print(f"\nTracks not found on Spotify ({len(report.unmatched_for_spotify)}):")
        for t in report.unmatched_for_spotify:
            print(f"  - {t}")

    if report.dry_run:
        print("\nNote: This was a dry run. No changes were committed to playlists.")
    else:
        print("\nSynchronization complete! Both playlists are up to date.")
    print("=" * 55)


def main():
    print_banner()

    parser = argparse.ArgumentParser(
        description="Bi-directional synchronization between Spotify and YouTube Music playlists."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: sync
    sync_parser = subparsers.add_parser("sync", help="Run bi-directional playlist sync")
    sync_parser.add_argument("-s", "--spotify", help="Spotify playlist URL or ID")
    sync_parser.add_argument("-y", "--ytmusic", help="YouTube Music playlist URL or ID")
    sync_parser.add_argument("--dry-run", action="store_true", help="Simulate sync without modifying playlists")
    sync_parser.add_argument("--min-score", type=float, default=70.0, help="Minimum fuzzy match score (0-100, default 70.0)")
    sync_parser.add_argument("--cache", default="sync_cache.json", help="Path to cache file for mapped tracks")
    sync_parser.add_argument("--yt-auth", help="Explicit path to YouTube Music auth file (oauth.json or browser.json)")
    sync_parser.add_argument("--direction", choices=["both", "yt-to-sp", "sp-to-yt"], default="both", help="Sync direction: 'both', 'yt-to-sp', or 'sp-to-yt'")
    sync_parser.set_defaults(func=cmd_sync)

    # Command: test
    test_parser = subparsers.add_parser("test", help="Test authentication status for both services")
    test_parser.add_argument("--yt-auth", help="Path to YouTube Music auth file")
    test_parser.set_defaults(func=cmd_test)

    # Command: setup-spotify
    setup_sp_parser = subparsers.add_parser("setup-spotify", help="Configure Spotify API credentials")
    setup_sp_parser.set_defaults(func=cmd_setup_spotify)

    # Command: setup-ytmusic
    setup_yt_parser = subparsers.add_parser("setup-ytmusic", help="Configure YouTube Music authentication")
    setup_yt_parser.set_defaults(func=cmd_setup_ytmusic)

    args = parser.parse_args()

    if not args.command:
        # Default to interactive sync if no subcommand provided
        cmd_sync(argparse.Namespace(
            spotify=None,
            ytmusic=None,
            dry_run=False,
            min_score=70.0,
            cache="sync_cache.json",
            yt_auth=None,
        ))
    else:
        args.func(args)


if __name__ == "__main__":
    main()
