import os
import re
from typing import List, Optional, Tuple
from ytmusicapi import YTMusic

from .matcher import Track, calculate_match_score, clean_title, clean_artist


def extract_ytmusic_playlist_id(url_or_id: str) -> str:
    """Extracts raw YouTube Music playlist ID from URL or ID string."""
    cleaned = url_or_id.strip()
    match = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", cleaned)
    if match:
        return match.group(1)
    return cleaned


class YTMusicClient:
    def __init__(self, auth_file: Optional[str] = None):
        """
        Initializes the YouTube Music client.
        Checks for oauth.json or browser.json if auth_file is not explicitly provided.
        """
        self.auth_file = auth_file
        if not self.auth_file:
            # Check default locations
            if os.path.exists("oauth.json"):
                self.auth_file = "oauth.json"
            elif os.path.exists("browser.json"):
                self.auth_file = "browser.json"

        if self.auth_file and os.path.exists(self.auth_file):
            self.yt = YTMusic(self.auth_file)
            self.is_authenticated = True
        else:
            # Unauthenticated instance can search, but cannot modify playlists
            self.yt = YTMusic()
            self.is_authenticated = False

    def require_auth(self):
        """Raises an exception if client is not authenticated."""
        if not self.is_authenticated:
            raise PermissionError(
                "YouTube Music authentication is required to access or modify playlists.\n"
                "Please run: python sync.py setup-ytmusic\n"
                "Or provide browser.json / oauth.json in the project root."
            )

    def test_connection(self) -> dict:
        """Tests authentication status and returns user/account info if authenticated."""
        self.require_auth()
        # Fetching liked songs or library playlists verifies valid credentials
        library = self.yt.get_library_playlists(limit=1)
        return {
            "authenticated": True,
            "auth_file": self.auth_file,
            "library_playlists_found": len(library),
        }

    def get_playlist_details(self, playlist_id: str) -> dict:
        """Fetches basic metadata for a playlist."""
        pid = extract_ytmusic_playlist_id(playlist_id)
        res = self.yt.get_playlist(pid, limit=1)
        return {
            "id": res.get("id", pid),
            "title": res.get("title", ""),
            "description": res.get("description", ""),
            "total_tracks": res.get("trackCount", 0),
        }

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        """Fetches all tracks from a YouTube Music playlist."""
        pid = extract_ytmusic_playlist_id(playlist_id)
        res = self.yt.get_playlist(pid, limit=None)
        raw_tracks = res.get("tracks", [])

        tracks: List[Track] = []
        for item in raw_tracks:
            video_id = item.get("videoId")
            if not video_id:
                continue

            raw_artists = item.get("artists", [])
            artists = [a["name"] for a in raw_artists if isinstance(a, dict) and "name" in a]
            dur_sec = item.get("duration_seconds")

            track = Track(
                title=item.get("title", ""),
                artists=artists,
                duration_seconds=dur_sec,
                ytmusic_id=video_id,
            )
            tracks.append(track)

        return tracks

    def search_track(self, track: Track, min_score: float = 70.0) -> Optional[Tuple[Track, float]]:
        """
        Searches YouTube Music for the best matching song.
        Returns (Track, score) or None.
        """
        c_title = clean_title(track.title)
        c_artist = clean_artist(track.primary_artist)

        search_strategies = [
            (f"{c_title} {c_artist}".strip(), "songs"),
            (f"{c_title} {c_artist}".strip(), "videos"),
            (f"{c_title}".strip(), "songs"),
        ]

        best_match: Optional[Track] = None
        best_score = 0.0

        for query, filter_type in search_strategies:
            if not query:
                continue

            try:
                results = self.yt.search(query, filter=filter_type, limit=10)
            except Exception:
                continue

            for item in results:
                video_id = item.get("videoId")
                if not video_id:
                    continue

                raw_artists = item.get("artists", [])
                artists = [a["name"] for a in raw_artists if isinstance(a, dict) and "name" in a]
                dur_sec = item.get("duration_seconds")

                score = calculate_match_score(
                    track.title,
                    track.artists,
                    track.duration_seconds,
                    item.get("title", ""),
                    artists,
                    dur_sec,
                )

                if score > best_score:
                    best_score = score
                    best_match = Track(
                        title=item.get("title", ""),
                        artists=artists,
                        duration_seconds=dur_sec,
                        ytmusic_id=video_id,
                    )

            if best_score >= 85.0:
                break

        if best_match and best_score >= min_score:
            return best_match, best_score
        return None

    def add_tracks_to_playlist(self, playlist_id: str, tracks: List[Track]) -> int:
        """
        Adds tracks to a YouTube Music playlist.
        Returns the number of tracks attempted/added.
        """
        self.require_auth()
        pid = extract_ytmusic_playlist_id(playlist_id)
        video_ids = [t.ytmusic_id for t in tracks if t.ytmusic_id]
        if not video_ids:
            return 0

        # ytmusicapi add_playlist_items accepts list of videoIds
        # Batches of 50 are safest
        batch_size = 50
        added_count = 0
        for i in range(0, len(video_ids), batch_size):
            chunk = video_ids[i : i + batch_size]
            try:
                self.yt.add_playlist_items(pid, chunk, duplicates=False)
                added_count += len(chunk)
            except Exception as e:
                # If duplicates=False raises an error when duplicates exist,
                # fall back to individual additions
                for vid in chunk:
                    try:
                        self.yt.add_playlist_items(pid, [vid], duplicates=False)
                        added_count += 1
                    except Exception:
                        pass

        return added_count
