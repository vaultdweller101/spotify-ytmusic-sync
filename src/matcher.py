import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from rapidfuzz import fuzz


@dataclass
class Track:
    title: str
    artists: List[str] = field(default_factory=list)
    duration_seconds: Optional[int] = None
    spotify_id: Optional[str] = None
    spotify_uri: Optional[str] = None
    ytmusic_id: Optional[str] = None
    isrc: Optional[str] = None

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    @property
    def artists_str(self) -> str:
        return ", ".join(self.artists) if self.artists else ""

    def __str__(self) -> str:
        artists = f" - {self.artists_str}" if self.artists_str else ""
        dur = f" ({self.duration_seconds // 60}:{self.duration_seconds % 60:02d})" if self.duration_seconds else ""
        return f"{self.title}{artists}{dur}"


def clean_title(title: str) -> str:
    """Removes common extraneous video tags, remasters, and parentheticals from titles."""
    if not title:
        return ""

    t = title

    # Remove (Official Video), [Official Audio], (Lyric Video), (Live), etc.
    tags = [
        r"\(official\s*(?:music)?\s*(?:video|audio|lyric\s*video|lyrics?|visualizer|track)\)",
        r"\[official\s*(?:music)?\s*(?:video|audio|lyric\s*video|lyrics?|visualizer|track)\]",
        r"\((?:audio|lyrics?|lyric\s*video|visualizer|video|live|hd|4k|mv|hq)\)",
        r"\[(?:audio|lyrics?|lyric\s*video|visualizer|video|live|hd|4k|mv|hq)\]",
        r"\((?:[0-9]{4}\s*)?remaster(?:ed)?(?:\s*[0-9]{4})?\)",
        r"\[(?:[0-9]{4}\s*)?remaster(?:ed)?(?:\s*[0-9]{4})?\]",
        r"-\s*(?:[0-9]{4}\s*)?remaster(?:ed)?(?:\s*[0-9]{4})?",
        r"-\s*single\s*version",
        r"-\s*radio\s*edit",
    ]

    for pattern in tags:
        t = re.sub(pattern, "", t, flags=re.IGNORECASE)

    # Normalize featured artists in title: (feat. X) -> X
    t = re.sub(r"[\(\[](?:feat|ft)\.?\s+([^\)\]]+)[\)\]]", r"\1", t, flags=re.IGNORECASE)

    # Clean whitespace and trailing punctuation
    t = re.sub(r"\s+", " ", t).strip(" -_")
    return t


def clean_artist(artist: str) -> str:
    """Normalizes artist name."""
    if not artist:
        return ""
    a = artist.lower()
    # Remove leading 'the '
    if a.startswith("the "):
        a = a[4:]
    return a.strip()


def calculate_match_score(
    title1: str,
    artists1: List[str],
    duration1: Optional[int],
    title2: str,
    artists2: List[str],
    duration2: Optional[int],
) -> float:
    """
    Computes a composite similarity score (0 - 100) between two tracks.
    Takes into account cleaned title similarity, artist similarity, and duration difference.
    """
    clean_t1 = clean_title(title1)
    clean_t2 = clean_title(title2)

    # Title score: combination of token_set_ratio and partial_ratio
    title_score = max(
        fuzz.token_set_ratio(clean_t1, clean_t2),
        fuzz.token_sort_ratio(clean_t1, clean_t2),
    )

    # Artist score
    artists_str1 = " ".join(clean_artist(a) for a in artists1)
    artists_str2 = " ".join(clean_artist(a) for a in artists2)

    if artists_str1 and artists_str2:
        # Check if primary artist matches or is contained
        primary1 = clean_artist(artists1[0]) if artists1 else ""
        primary2 = clean_artist(artists2[0]) if artists2 else ""

        if primary1 and primary2 and (primary1 in primary2 or primary2 in primary1):
            artist_score = 95.0
        else:
            artist_score = max(
                fuzz.token_set_ratio(artists_str1, artists_str2),
                fuzz.token_sort_ratio(artists_str1, artists_str2),
            )
    else:
        # If artist info is missing, default to neutral
        artist_score = 65.0

    # Base weighted score: 60% title, 40% artist
    total_score = (0.60 * title_score) + (0.40 * artist_score)

    # Duration check (if both are known)
    if duration1 is not None and duration2 is not None:
        diff = abs(duration1 - duration2)
        if diff <= 4:
            total_score = min(100.0, total_score + 5.0)
        elif diff > 35:
            # Substantial difference in duration (>35s) -> likely a live version, extended mix, or video intro
            total_score -= min(40.0, (diff - 35) * 1.0)

    return max(0.0, total_score)


def is_match(track1: Track, track2: Track, threshold: float = 75.0) -> Tuple[bool, float]:
    """Determines whether two tracks are considered a match."""
    score = calculate_match_score(
        track1.title,
        track1.artists,
        track1.duration_seconds,
        track2.title,
        track2.artists,
        track2.duration_seconds,
    )
    return score >= threshold, score
