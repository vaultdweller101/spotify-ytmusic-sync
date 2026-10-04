import os
import re
from typing import List, Optional, Tuple
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .matcher import Track, calculate_match_score, clean_title, clean_artist


def extract_spotify_playlist_id(url_or_id: str) -> str:
    """Extracts raw Spotify playlist ID from URL, URI, or ID string."""
    cleaned = url_or_id.strip()
    # Match URL: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=...
    match_url = re.search(r"playlist[/:]([a-zA-Z0-9]+)", cleaned)
    if match_url:
        return match_url.group(1)
    return cleaned


class SpotifyClient:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        cache_path: str = ".spotify_token_cache",
    ):
        self.client_id = client_id or os.getenv("SPOTIPY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("SPOTIPY_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv(
            "SPOTIPY_REDIRECT_URI", "http://localhost:8888/callback"
        )

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Spotify Client ID and Client Secret are required. "
                "Please set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET in .env"
            )

        self.scope = (
            "playlist-read-private "
            "playlist-read-collaborative "
            "playlist-modify-public "
            "playlist-modify-private"
        )

        self.auth_manager = SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
            cache_path=cache_path,
            open_browser=True,
        )
        self.sp = spotipy.Spotify(auth_manager=self.auth_manager)

    def test_connection(self) -> dict:
        """Verifies Spotify authentication and returns user profile."""
        return self.sp.current_user()

    def get_playlist_details(self, playlist_id: str) -> dict:
        """Fetches basic playlist metadata."""
        pid = extract_spotify_playlist_id(playlist_id)
        res = self.sp.playlist(pid, fields="id,name,description,tracks.total")
        return {
            "id": res["id"],
            "name": res["name"],
            "description": res.get("description", ""),
            "total_tracks": res.get("tracks", {}).get("total", 0),
        }

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        """Fetches all tracks from a Spotify playlist."""
        pid = extract_spotify_playlist_id(playlist_id)
        tracks: List[Track] = []
        offset = 0
        limit = 100

        while True:
            response = self.sp.playlist_items(
                pid,
                limit=limit,
                offset=offset,
                additional_types=["track"],
            )
            items = response.get("items", [])
            if not items:
                break

            for item in items:
                raw_track = item.get("track")
                if not raw_track or not raw_track.get("id"):
                    # Local files or deleted tracks might not have an id
                    continue

                artists = [a["name"] for a in raw_track.get("artists", [])]
                dur_sec = raw_track.get("duration_ms", 0) // 1000
                isrc = (
                    raw_track.get("external_ids", {}).get("isrc")
                    if raw_track.get("external_ids")
                    else None
                )

                track = Track(
                    title=raw_track.get("name", ""),
                    artists=artists,
                    duration_seconds=dur_sec if dur_sec > 0 else None,
                    spotify_id=raw_track["id"],
                    spotify_uri=raw_track.get("uri"),
                    isrc=isrc,
                )
                tracks.append(track)

            offset += len(items)
            if len(items) < limit:
                break

        return tracks

    def search_track(self, track: Track, min_score: float = 70.0) -> Optional[Tuple[Track, float]]:
        """
        Searches Spotify for the best matching track.
        Returns (Track, score) or None.
        """
        queries = []

        # 1. Search by ISRC if available
        if track.isrc:
            queries.append(f"isrc:{track.isrc}")

        c_title = clean_title(track.title)
        c_artist = clean_artist(track.primary_artist)

        # 2. Field-specific query
        if c_artist:
            queries.append(f"track:{c_title} artist:{c_artist}")
        # 3. Fallback relaxed query
        queries.append(f"{c_title} {c_artist}".strip())

        best_match: Optional[Track] = None
        best_score = 0.0

        for query in queries:
            try:
                results = self.sp.search(q=query, type="track", limit=10)
                items = results.get("tracks", {}).get("items", [])
            except Exception:
                continue

            for item in items:
                artists = [a["name"] for a in item.get("artists", [])]
                dur_sec = item.get("duration_ms", 0) // 1000
                cand_isrc = item.get("external_ids", {}).get("isrc") if item.get("external_ids") else None

                # Exact ISRC match is 100% confidence
                if track.isrc and cand_isrc and track.isrc.lower() == cand_isrc.lower():
                    matched_track = Track(
                        title=item["name"],
                        artists=artists,
                        duration_seconds=dur_sec,
                        spotify_id=item["id"],
                        spotify_uri=item["uri"],
                        isrc=cand_isrc,
                    )
                    return matched_track, 100.0

                score = calculate_match_score(
                    track.title,
                    track.artists,
                    track.duration_seconds,
                    item["name"],
                    artists,
                    dur_sec,
                )

                if score > best_score:
                    best_score = score
                    best_match = Track(
                        title=item["name"],
                        artists=artists,
                        duration_seconds=dur_sec,
                        spotify_id=item["id"],
                        spotify_uri=item["uri"],
                        isrc=cand_isrc,
                    )

            if best_score >= 85.0:
                break

        if best_match and best_score >= min_score:
            return best_match, best_score
        return None

    def add_tracks_to_playlist(self, playlist_id: str, tracks: List[Track]) -> int:
        """
        Adds tracks to a Spotify playlist in batches of up to 100.
        Returns the number of tracks added.
        """
        pid = extract_spotify_playlist_id(playlist_id)
        uris = [t.spotify_uri for t in tracks if t.spotify_uri]
        if not uris:
            return 0

        # Batch in chunks of 100
        added_count = 0
        batch_size = 100
        for i in range(0, len(uris), batch_size):
            chunk = uris[i : i + batch_size]
            self.sp.playlist_add_items(pid, chunk)
            added_count += len(chunk)

        return added_count
