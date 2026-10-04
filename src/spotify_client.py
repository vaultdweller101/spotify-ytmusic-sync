import os
import re
import json
import subprocess
import urllib.request
import urllib.parse
from typing import List, Optional, Tuple

from .matcher import Track, calculate_match_score, clean_title, clean_artist


def extract_spotify_playlist_id(url_or_id: str) -> str:
    """Extracts raw Spotify playlist ID from URL, URI, or ID string."""
    cleaned = url_or_id.strip()
    match_url = re.search(r"playlist[/:]([a-zA-Z0-9]+)", cleaned)
    if match_url:
        return match_url.group(1)
    return cleaned


class SpotifyPublicClient:
    """
    Interacts with Spotify without requiring any developer account,
    API keys, or Spotify Premium.
    - Reads playlists of ANY size using Spotify's public partner endpoints.
    - Resolves Spotify track URIs publicly.
    """
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

    def get_playlist_details(self, playlist_id: str) -> dict:
        pid = extract_spotify_playlist_id(playlist_id)
        try:
            import spotapi
            pl = spotapi.PublicPlaylist(pid)
            info = pl.get_playlist_info(limit=1)
            content = info.get("data", {}).get("playlistV2", {}).get("content", {})
            name = info.get("data", {}).get("playlistV2", {}).get("name", f"Spotify Playlist ({pid})")
            return {
                "id": pid,
                "name": name,
                "description": "",
                "total_tracks": content.get("totalCount", 0),
            }
        except Exception:
            pass

        url = f"https://open.spotify.com/embed/playlist/{pid}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
            matches = re.findall(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if matches:
                data = json.loads(matches[0])
                entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                return {
                    "id": pid,
                    "name": entity.get("title", f"Spotify Playlist ({pid})"),
                    "description": entity.get("subtitle", ""),
                    "total_tracks": len(entity.get("trackList", [])),
                }
        except Exception as e:
            print(f"[Warning] Could not fetch embed details for {pid}: {e}")

        return {
            "id": pid,
            "name": f"Spotify Playlist ({pid})",
            "description": "",
            "total_tracks": 0,
        }

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        pid = extract_spotify_playlist_id(playlist_id)
        tracks: List[Track] = []

        # 1. Primary method: spotapi paginated extraction (handles 1,000+ tracks)
        try:
            import spotapi
            pl = spotapi.PublicPlaylist(pid)
            for batch in pl.paginate_playlist():
                items = batch.get("items", [])
                for it in items:
                    data = it.get("itemV2", {}).get("data", {})
                    name = data.get("name")
                    if not name:
                        continue
                    artists = [
                        a.get("profile", {}).get("name")
                        for a in data.get("artists", {}).get("items", [])
                        if a.get("profile", {}).get("name")
                    ]
                    uri = data.get("uri")
                    dur_data = data.get("trackDuration", {})
                    dur_ms = dur_data.get("totalMilliseconds") if isinstance(dur_data, dict) else None
                    dur_sec = dur_ms // 1000 if dur_ms else None

                    track = Track(
                        title=name,
                        artists=artists,
                        duration_seconds=dur_sec,
                        spotify_uri=uri,
                        spotify_id=uri.split(":")[-1] if uri else None,
                    )
                    tracks.append(track)
            if tracks:
                return tracks
        except Exception as e:
            print(f"[Notice] spotapi public fetch error ({e}), trying embed parser.")

        # 2. Fallback method: web embed parser (first 100 tracks)
        url = f"https://open.spotify.com/embed/playlist/{pid}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
            matches = re.findall(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if matches:
                data = json.loads(matches[0])
                entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                track_list = entity.get("trackList", [])
                for item in track_list:
                    uri = item.get("uri")
                    title = item.get("title", "")
                    subtitle = item.get("subtitle", "")
                    artists = [a.strip() for a in subtitle.split(",")] if subtitle else []
                    dur_ms = item.get("duration", 0)

                    track = Track(
                        title=title,
                        artists=artists,
                        duration_seconds=dur_ms // 1000 if dur_ms else None,
                        spotify_uri=uri,
                        spotify_id=uri.split(":")[-1] if uri else None,
                    )
                    tracks.append(track)
        except Exception as e:
            print(f"[Error] Failed to fetch Spotify embed tracks: {e}")

        return tracks

    def search_track(self, track: Track, min_score: float = 70.0) -> Optional[Tuple[Track, float]]:
        """
        Publicly finds the Spotify track URI without official API keys.
        Uses spotapi direct Spotify search first, then DuckDuckGo as fallback.
        """
        c_title = clean_title(track.title)
        c_artist = clean_artist(track.primary_artist)
        query = f"{c_title} {c_artist}".strip()

        # 1. Primary: spotapi direct search
        try:
            import spotapi
            results = spotapi.Public.song_search(query)
            items = next(results)
            if isinstance(items, list):
                best_match: Optional[Track] = None
                best_score = 0.0
                for it in items[:6]:
                    d = it.get("item", {}).get("data", {})
                    name = d.get("name")
                    if not name:
                        continue
                    artists = [
                        a.get("profile", {}).get("name")
                        for a in d.get("artists", {}).get("items", [])
                        if a.get("profile", {}).get("name")
                    ]
                    dur_data = d.get("duration", {})
                    dur_ms = dur_data.get("totalMilliseconds") if isinstance(dur_data, dict) else None
                    dur_sec = dur_ms // 1000 if dur_ms else None
                    uri = d.get("uri")
                    track_id = uri.split(":")[-1] if uri else None

                    score = calculate_match_score(
                        track.title,
                        track.artists,
                        track.duration_seconds,
                        name,
                        artists,
                        dur_sec,
                    )
                    if score > best_score:
                        best_score = score
                        best_match = Track(
                            title=name,
                            artists=artists,
                            duration_seconds=dur_sec,
                            spotify_id=track_id,
                            spotify_uri=uri,
                        )

                if best_match and best_score >= min_score:
                    return best_match, best_score
        except Exception:
            pass

        # 2. Fallback: DuckDuckGo search
        ddg_query = f"site:open.spotify.com/track {c_title} {c_artist}".strip()
        data = urllib.parse.urlencode({"q": ddg_query}).encode("utf-8")
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/",
            data=data,
            headers=self.headers,
        )

        try:
            html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8")
            matches = re.findall(r'open\.spotify\.com/track/([a-zA-Z0-9]{22})', html)
            if matches:
                track_id = matches[0]
                matched_track = Track(
                    title=track.title,
                    artists=track.artists,
                    duration_seconds=track.duration_seconds,
                    spotify_id=track_id,
                    spotify_uri=f"spotify:track:{track_id}",
                )
                return matched_track, 85.0
        except Exception:
            pass

        return None


class SpotifyClient:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        cache_path: str = ".spotify_token_cache",
        force_free_mode: bool = False,
    ):
        self.client_id = client_id or os.getenv("SPOTIPY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("SPOTIPY_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv(
            "SPOTIPY_REDIRECT_URI", "http://localhost:8888/callback"
        )
        self.force_free_mode = force_free_mode
        self.has_write_access = False
        self.public_client = SpotifyPublicClient()
        self.sp = None

        if not self.force_free_mode and self.client_id and self.client_secret:
            try:
                import spotipy
                from spotipy.oauth2 import SpotifyOAuth

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
                self.has_write_access = True
            except Exception as e:
                print(f"[Notice] Official Spotify API auth failed ({e}). Falling back to Free / Public mode.")
                self.has_write_access = False
        else:
            self.has_write_access = False

    def test_connection(self) -> dict:
        if self.has_write_access and self.sp:
            user = self.sp.current_user()
            return {
                "mode": "Official Web API (Full Read/Write)",
                "display_name": user.get("display_name"),
                "id": user.get("id"),
            }
        else:
            return {
                "mode": "Free / Public Mode (Zero-API / No Premium required)",
                "display_name": "Public Scraper Mode",
                "id": "public",
            }

    def get_playlist_details(self, playlist_id: str) -> dict:
        if self.has_write_access and self.sp:
            try:
                pid = extract_spotify_playlist_id(playlist_id)
                res = self.sp.playlist(pid, fields="id,name,description,tracks.total")
                return {
                    "id": res["id"],
                    "name": res["name"],
                    "description": res.get("description", ""),
                    "total_tracks": res.get("tracks", {}).get("total", 0),
                }
            except Exception:
                pass
        return self.public_client.get_playlist_details(playlist_id)

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        if self.has_write_access and self.sp:
            try:
                pid = extract_spotify_playlist_id(playlist_id)
                tracks: List[Track] = []
                offset = 0
                limit = 100
                while True:
                    response = self.sp.playlist_items(
                        pid, limit=limit, offset=offset, additional_types=["track"]
                    )
                    items = response.get("items", [])
                    if not items:
                        break

                    for item in items:
                        raw_track = item.get("track")
                        if not raw_track or not raw_track.get("id"):
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
            except Exception as e:
                print(f"[Notice] Official API playlist fetch failed ({e}). Falling back to Free Public parser.")

        return self.public_client.get_playlist_tracks(playlist_id)

    def search_track(self, track: Track, min_score: float = 70.0) -> Optional[Tuple[Track, float]]:
        if self.has_write_access and self.sp:
            queries = []
            if track.isrc:
                queries.append(f"isrc:{track.isrc}")

            c_title = clean_title(track.title)
            c_artist = clean_artist(track.primary_artist)
            if c_artist:
                queries.append(f"track:{c_title} artist:{c_artist}")
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
                    cand_isrc = (
                        item.get("external_ids", {}).get("isrc")
                        if item.get("external_ids")
                        else None
                    )

                    if track.isrc and cand_isrc and track.isrc.lower() == cand_isrc.lower():
                        return Track(
                            title=item["name"],
                            artists=artists,
                            duration_seconds=dur_sec,
                            spotify_id=item["id"],
                            spotify_uri=item["uri"],
                            isrc=cand_isrc,
                        ), 100.0

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

        # Fallback to public search without API keys
        return self.public_client.search_track(track, min_score)

    def add_tracks_to_playlist(self, playlist_id: str, tracks: List[Track]) -> int:
        if self.has_write_access and self.sp:
            pid = extract_spotify_playlist_id(playlist_id)
            uris = [t.spotify_uri for t in tracks if t.spotify_uri and t.spotify_uri.startswith("spotify:track:")]
            if not uris:
                return 0

            added_count = 0
            batch_size = 100
            for i in range(0, len(uris), batch_size):
                chunk = uris[i : i + batch_size]
                self.sp.playlist_add_items(pid, chunk)
                added_count += len(chunk)
            return added_count
        else:
            # Free Mode: Extract track URIs/URLs, copy to Windows clipboard, and save to file
            output_file = "spotify_tracks_to_add.txt"
            urls_to_copy = []

            with open(output_file, "w", encoding="utf-8") as f:
                f.write("# Tracks from YouTube Music to add to Spotify\n")
                f.write("# The Spotify links below have been copied to your Windows Clipboard!\n")
                f.write("# Open Spotify Desktop, click anywhere in your playlist, and press Ctrl+V to add all of them!\n\n")
                for t in tracks:
                    track_url = f"https://open.spotify.com/track/{t.spotify_id}" if t.spotify_id else t.spotify_uri
                    if track_url:
                        urls_to_copy.append(track_url)
                        f.write(f"{track_url}\n")
                    else:
                        f.write(f"# (No direct link found) {t.title} - {t.artists_str}\n")

            # Copy to Windows clipboard via PowerShell
            if urls_to_copy:
                try:
                    joined_urls = "\n".join(urls_to_copy)
                    cmd = ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"]
                    subprocess.run(cmd, input=joined_urls, text=True, check=True)
                    clipboard_copied = True
                except Exception:
                    clipboard_copied = False
            else:
                clipboard_copied = False

            print("\n" + "=" * 60)
            print("         YOUTUBE MUSIC -> SPOTIFY (FREE MODE)")
            print("=" * 60)
            print(f"Found {len(tracks)} track(s) from YouTube Music to add to Spotify.")
            print(f"Saved track links to: {output_file}")
            if clipboard_copied:
                print("\n[COPIED TO CLIPBOARD!] All Spotify track links are now on your clipboard.")
                print(">>> How to add them to Spotify in 3 seconds:")
                print("    1. Open the Spotify Desktop app.")
                print("    2. Navigate to your target playlist.")
                print("    3. Click inside the playlist area and press Ctrl + V.")
                print("    4. All songs will be instantly added!")
            else:
                print("\nTip: Copy the links from 'spotify_tracks_to_add.txt', select your playlist in Spotify Desktop, and press Ctrl+V.")
            print("=" * 60 + "\n")

            return len(tracks)
