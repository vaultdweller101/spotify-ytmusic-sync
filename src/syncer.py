import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from .matcher import Track, is_match
from .spotify_client import SpotifyClient
from .ytmusic_client import YTMusicClient


@dataclass
class SyncReport:
    spotify_total: int = 0
    ytmusic_total: int = 0
    already_synced_count: int = 0
    added_to_ytmusic: List[Track] = field(default_factory=list)
    added_to_spotify: List[Track] = field(default_factory=list)
    unmatched_for_ytmusic: List[Track] = field(default_factory=list)
    unmatched_for_spotify: List[Track] = field(default_factory=list)
    dry_run: bool = False


class PlaylistSyncer:
    def __init__(
        self,
        spotify_client: SpotifyClient,
        ytmusic_client: YTMusicClient,
        cache_path: str = "sync_cache.json",
        min_match_score: float = 70.0,
    ):
        self.sp = spotify_client
        self.yt = ytmusic_client
        self.cache_path = cache_path
        self.min_match_score = min_match_score
        self.cache: Dict[str, str] = self._load_cache()

    def _load_cache(self) -> Dict[str, str]:
        """Loads known matches from cache file."""
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("matches", {})
            except Exception:
                return {}
        return {}

    def _save_cache(self):
        """Saves known matches to cache file."""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({"matches": self.cache}, f, indent=2)
        except Exception as e:
            print(f"[Warning] Failed to save sync cache: {e}")

    def sync(
        self,
        spotify_playlist_id: str,
        ytmusic_playlist_id: str,
        dry_run: bool = False,
    ) -> SyncReport:
        """
        Executes a two-way synchronization between a Spotify playlist and a YouTube Music playlist.
        Tracks present on Spotify but missing on YTM are searched and added to YTM.
        Tracks present on YTM but missing on Spotify are searched and added to Spotify.
        """
        report = SyncReport(dry_run=dry_run)

        print("\n=== Fetching Playlists ===")
        sp_meta = self.sp.get_playlist_details(spotify_playlist_id)
        yt_meta = self.yt.get_playlist_details(ytmusic_playlist_id)

        print(f"Spotify Playlist:      '{sp_meta['name']}' ({sp_meta['total_tracks']} tracks)")
        print(f"YouTube Music Playlist: '{yt_meta['title']}' ({yt_meta['total_tracks']} tracks)")

        sp_tracks = self.sp.get_playlist_tracks(spotify_playlist_id)
        yt_tracks = self.yt.get_playlist_tracks(ytmusic_playlist_id)

        report.spotify_total = len(sp_tracks)
        report.ytmusic_total = len(yt_tracks)

        print(f"\nRetrieved {len(sp_tracks)} tracks from Spotify and {len(yt_tracks)} tracks from YouTube Music.")
        print("Comparing existing tracks across both playlists...")

        # Build reverse index for fast cache lookup
        yt_id_to_sp_id = {v: k for k, v in self.cache.items()}

        # Identify tracks that are already in both playlists
        matched_sp_ids = set()
        matched_yt_ids = set()

        for sp_t in sp_tracks:
            # 1. Check cache
            cached_yt_id = self.cache.get(sp_t.spotify_id)
            if cached_yt_id:
                for yt_t in yt_tracks:
                    if yt_t.ytmusic_id == cached_yt_id:
                        matched_sp_ids.add(sp_t.spotify_id)
                        matched_yt_ids.add(yt_t.ytmusic_id)
                        break

            # 2. Fuzzy match against current YTM tracks
            if sp_t.spotify_id not in matched_sp_ids:
                for yt_t in yt_tracks:
                    if yt_t.ytmusic_id in matched_yt_ids:
                        continue
                    matched, score = is_match(sp_t, yt_t, self.min_match_score)
                    if matched:
                        matched_sp_ids.add(sp_t.spotify_id)
                        matched_yt_ids.add(yt_t.ytmusic_id)
                        if sp_t.spotify_id and yt_t.ytmusic_id:
                            self.cache[sp_t.spotify_id] = yt_t.ytmusic_id
                        break

        already_synced = len(matched_sp_ids)
        report.already_synced_count = already_synced
        print(f"Found {already_synced} tracks already synchronized in both playlists.")

        # Determine missing tracks in each direction
        missing_in_ytm = [t for t in sp_tracks if t.spotify_id not in matched_sp_ids]
        missing_in_spotify = [t for t in yt_tracks if t.ytmusic_id not in matched_yt_ids]

        print(f"\nTracks to sync to YouTube Music: {len(missing_in_ytm)}")
        print(f"Tracks to sync to Spotify:       {len(missing_in_spotify)}")

        # Step 1: Spotify -> YouTube Music
        to_add_ytm: List[Track] = []
        if missing_in_ytm:
            print("\nSearching YouTube Music for missing tracks...")
            for i, sp_t in enumerate(missing_in_ytm, 1):
                print(f"  [{i}/{len(missing_in_ytm)}] Searching YTM: {sp_t}")
                # Check cache first
                cached_vid = self.cache.get(sp_t.spotify_id)
                found_track = None
                if cached_vid:
                    found_track = Track(title=sp_t.title, artists=sp_t.artists, ytmusic_id=cached_vid)
                else:
                    match_res = self.yt.search_track(sp_t, min_score=self.min_match_score)
                    if match_res:
                        found_track, score = match_res
                        print(f"      -> Matched: '{found_track}' (confidence {score:.1f}%)")
                        if sp_t.spotify_id and found_track.ytmusic_id:
                            self.cache[sp_t.spotify_id] = found_track.ytmusic_id

                if found_track:
                    to_add_ytm.append(found_track)
                else:
                    print(f"      -> [No match found on YouTube Music]")
                    report.unmatched_for_ytmusic.append(sp_t)

        # Step 2: YouTube Music -> Spotify
        to_add_spotify: List[Track] = []
        if missing_in_spotify:
            print("\nSearching Spotify for missing tracks...")
            for i, yt_t in enumerate(missing_in_spotify, 1):
                print(f"  [{i}/{len(missing_in_spotify)}] Searching Spotify: {yt_t}")
                # Check cache first
                cached_sp_id = yt_id_to_sp_id.get(yt_t.ytmusic_id)
                found_track = None
                if cached_sp_id:
                    found_track = Track(
                        title=yt_t.title,
                        artists=yt_t.artists,
                        spotify_id=cached_sp_id,
                        spotify_uri=f"spotify:track:{cached_sp_id}",
                    )
                else:
                    match_res = self.sp.search_track(yt_t, min_score=self.min_match_score)
                    if match_res:
                        found_track, score = match_res
                        print(f"      -> Matched: '{found_track}' (confidence {score:.1f}%)")
                        if found_track.spotify_id and yt_t.ytmusic_id:
                            self.cache[found_track.spotify_id] = yt_t.ytmusic_id

                if found_track:
                    to_add_spotify.append(found_track)
                else:
                    print(f"      -> [No match found on Spotify]")
                    report.unmatched_for_spotify.append(yt_t)

        report.added_to_ytmusic = to_add_ytm
        report.added_to_spotify = to_add_spotify

        # Save cache with newly discovered pairings
        self._save_cache()

        # Step 3: Apply modifications
        if dry_run:
            print("\n[DRY RUN] Skipping playlist modifications.")
        else:
            if to_add_ytm:
                print(f"\nAdding {len(to_add_ytm)} track(s) to YouTube Music playlist...")
                added = self.yt.add_tracks_to_playlist(ytmusic_playlist_id, to_add_ytm)
                print(f"Successfully added {added} track(s) to YouTube Music.")

            if to_add_spotify:
                print(f"\nAdding {len(to_add_spotify)} track(s) to Spotify playlist...")
                added = self.sp.add_tracks_to_playlist(spotify_playlist_id, to_add_spotify)
                print(f"Successfully added {added} track(s) to Spotify.")

        return report
