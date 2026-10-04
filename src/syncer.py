import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from .matcher import Track, is_match, clean_title, clean_artist
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
        direction: str = "both",
    ) -> SyncReport:
        """
        Executes synchronization between a Spotify playlist and a YouTube Music playlist.
        direction can be: 'both', 'yt-to-sp' (YouTube Music to Spotify), or 'sp-to-yt' (Spotify to YouTube Music).
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

        # Build index for Spotify tracks by cleaned title for O(1) lookup
        sp_title_index = {}
        for sp_t in sp_tracks:
            c_title = clean_title(sp_t.title).lower()
            if c_title not in sp_title_index:
                sp_title_index[c_title] = []
            sp_title_index[c_title].append(sp_t)

        matched_sp_ids = set()
        matched_yt_ids = set()

        # Step 0: Check known cached matches
        for sp_t in sp_tracks:
            cached_yt_id = self.cache.get(sp_t.spotify_id)
            if cached_yt_id:
                for yt_t in yt_tracks:
                    if yt_t.ytmusic_id == cached_yt_id:
                        matched_sp_ids.add(sp_t.spotify_id)
                        matched_yt_ids.add(yt_t.ytmusic_id)
                        break

        # Pass 1: Fast title index matches
        for yt_t in yt_tracks:
            if yt_t.ytmusic_id in matched_yt_ids:
                continue
            c_yt = clean_title(yt_t.title).lower()
            if c_yt in sp_title_index:
                for sp_t in sp_title_index[c_yt]:
                    if sp_t.spotify_id in matched_sp_ids:
                        continue
                    matched, score = is_match(sp_t, yt_t, self.min_match_score)
                    if matched:
                        matched_sp_ids.add(sp_t.spotify_id)
                        matched_yt_ids.add(yt_t.ytmusic_id)
                        if sp_t.spotify_id and yt_t.ytmusic_id:
                            self.cache[sp_t.spotify_id] = yt_t.ytmusic_id
                        break

        # Pass 2: Fuzzy matches for remaining tracks
        remaining_yt = [t for t in yt_tracks if t.ytmusic_id not in matched_yt_ids]
        remaining_sp = [t for t in sp_tracks if t.spotify_id not in matched_sp_ids]

        for yt_t in remaining_yt:
            for sp_t in remaining_sp:
                if sp_t.spotify_id in matched_sp_ids:
                    continue
                matched, score = is_match(sp_t, yt_t, threshold=max(75.0, self.min_match_score))
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

        print(f"\nTracks in Spotify missing from YouTube Music: {len(missing_in_ytm)}")
        print(f"Tracks in YouTube Music missing from Spotify: {len(missing_in_spotify)}")

        # Step 1: Spotify -> YouTube Music (if direction includes it)
        to_add_ytm: List[Track] = []
        if direction in ("both", "sp-to-yt", "spotify-to-yt") and missing_in_ytm:
            print("\nSearching YouTube Music for missing tracks...")
            for i, sp_t in enumerate(missing_in_ytm, 1):
                print(f"  [{i}/{len(missing_in_ytm)}] Searching YTM: {sp_t}")
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

        # Step 2: YouTube Music -> Spotify (if direction includes it)
        to_add_spotify: List[Track] = []
        if direction in ("both", "yt-to-sp", "yt-to-spotify") and missing_in_spotify:
            print(f"\nSearching Spotify for {len(missing_in_spotify)} missing tracks...")
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
                try:
                    self.yt.require_auth()
                    added = self.yt.add_tracks_to_playlist(ytmusic_playlist_id, to_add_ytm)
                    print(f"Successfully added {added} track(s) to YouTube Music.")
                except Exception as e:
                    print(f"[Notice] Could not write to YouTube Music: {e}")
                    print("To allow adding tracks to YouTube Music, run: python sync.py setup-ytmusic")

            if to_add_spotify:
                print(f"\nAdding {len(to_add_spotify)} track(s) to Spotify playlist...")
                added = self.sp.add_tracks_to_playlist(spotify_playlist_id, to_add_spotify)
                print(f"Successfully added {added} track(s) to Spotify.")

        return report
