"""
Provider-independent 30-second preview fetcher (U4).

Replaces the deprecated Spotify `preview_url` path. Looks up a playable
30-second preview for a (song, artists) pair at query time from a free,
no-auth source: iTunes Search API (primary), Deezer (fallback).

Design notes:
- Spotify deprecated `preview_url` for dev-mode apps on 2024-11-27, so the
  old app.py path is likely already returning null. iTunes + Deezer are free,
  need no credentials, and each return a 30s preview.
- Preview URLs are NOT persisted (iTunes is stream-only; Deezer URLs are
  signed/expiring). We fetch live per query and keep only a small in-process
  cache to avoid duplicate lookups within a single render.
- Degrades gracefully: any network/parse error returns None so the caller
  renders no player rather than a broken one.
- Returns a store/link-out URL alongside the preview to honor iTunes' terms
  (store badge/link kept proximate to the preview).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

import requests

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
DEEZER_SEARCH_URL = "https://api.deezer.com/search"

# Conservative timeouts — mirrors the hardening lesson from the Spotify client:
# a slow third-party must never hang a render.
DEFAULT_TIMEOUT = 6.0

_USER_AGENT = "RabbitHole/0.1 (jorsanto@umich.edu)"


@dataclass(frozen=True)
class Preview:
    """A playable preview and where to hear the full track."""

    preview_url: str
    provider: str  # "itunes" | "deezer"
    store_url: Optional[str]  # link-out to the full track (Apple Music / Deezer)
    matched_title: Optional[str] = None
    matched_artist: Optional[str] = None
    artwork_url: Optional[str] = None  # album cover thumbnail
    album: Optional[str] = None        # album / collection name
    year: Optional[int] = None         # release year


# Process-lifetime cache keyed by (song, artists-tuple). Values are Preview | None.
# Kept intentionally simple; cleared only on process restart.
_CACHE: dict = {}


def _normalize(text: str) -> str:
    """Loose normalization for fuzzy title/artist comparison."""
    text = text.lower()
    # Drop parentheticals/brackets and "feat." clauses — they cause spurious mismatches.
    text = re.sub(r"[\(\[].*?[\)\]]", " ", text)
    text = re.sub(r"\b(feat|ft|featuring|with)\b.*", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(text.split())


def _title_matches(query_song: str, candidate_title: str) -> bool:
    """True if the candidate title plausibly matches the requested song."""
    q = _normalize(query_song)
    c = _normalize(candidate_title)
    if not q or not c:
        return False
    if q == c:
        return True
    # Substring either direction handles "song" vs "song (remaster)" etc.
    return q in c or c in q


def _artist_matches(artist_names: List[str], candidate_artist: str) -> bool:
    """True if at least one of the connecting artists appears in the candidate
    track's artist field. Prevents matching a same-titled song by an unrelated
    artist (e.g. Ice Cube's "Really Doe" for a Kendrick/Earl connection)."""
    cand = _normalize(candidate_artist)
    if not cand:
        return False
    for a in artist_names:
        na = _normalize(a)
        # Require a reasonably specific name to avoid 2-letter false positives.
        if len(na) >= 3 and (na in cand or cand in na):
            return True
    return False


def _accept(query_song: str, artist_names: List[str], title: str, artist: str) -> bool:
    """A candidate is only accepted if BOTH its title and its artist match the
    request. No 'first result with a preview' fallback — a wrong preview is
    worse than none, so unmatched queries degrade to no player."""
    return _title_matches(query_song, title) and _artist_matches(artist_names, artist)


def _year_from(datestr: Optional[str]) -> Optional[int]:
    """Parse a leading 4-digit year from an ISO-ish date (e.g. '2005-08-29T...')."""
    if not datestr or len(datestr) < 4 or not datestr[:4].isdigit():
        return None
    return int(datestr[:4])


def _build_term(song_name: str, artist_names: List[str]) -> str:
    artists = " ".join(a for a in artist_names if a)
    return f"{song_name} {artists}".strip()


def _try_itunes(song_name: str, artist_names: List[str], timeout: float) -> Optional[Preview]:
    params = {
        "term": _build_term(song_name, artist_names),
        "media": "music",
        "entity": "song",
        "limit": 5,
    }
    resp = requests.get(
        ITUNES_SEARCH_URL, params=params, timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    # Only accept a track whose title AND artist match; no lenient fallback.
    for track in results:
        preview = track.get("previewUrl")
        if not preview:
            continue
        if _accept(song_name, artist_names, track.get("trackName", ""), track.get("artistName", "")):
            # artworkUrl100 is 100px; bump to 300px for a crisper thumbnail.
            art = track.get("artworkUrl100")
            if art:
                art = art.replace("100x100", "300x300")
            return Preview(
                preview_url=preview,
                provider="itunes",
                store_url=track.get("trackViewUrl"),
                matched_title=track.get("trackName"),
                matched_artist=track.get("artistName"),
                artwork_url=art,
                album=track.get("collectionName"),
                year=_year_from(track.get("releaseDate")),
            )
    return None


def _try_deezer(song_name: str, artist_names: List[str], timeout: float) -> Optional[Preview]:
    params = {"q": _build_term(song_name, artist_names), "limit": 5}
    resp = requests.get(
        DEEZER_SEARCH_URL, params=params, timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    results = resp.json().get("data", [])
    for track in results:
        preview = track.get("preview")
        if not preview:
            continue
        artist = (track.get("artist") or {}).get("name", "")
        if _accept(song_name, artist_names, track.get("title", ""), artist):
            album = track.get("album") or {}
            return Preview(
                preview_url=preview,
                provider="deezer",
                store_url=track.get("link"),
                matched_title=track.get("title"),
                matched_artist=artist,
                artwork_url=album.get("cover_medium"),
                album=album.get("title"),
                year=None,  # not present in Deezer search results
            )
    return None


def get_preview(
    song_name: str,
    artist_names: Optional[List[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
) -> Optional[Preview]:
    """
    Return a Preview for a (song, artists) pair, or None if no preview is found.

    Tries iTunes first, then Deezer. Never raises on network/parse errors — a
    failure in either provider falls through to the next, and total failure
    returns None so the caller degrades gracefully.
    """
    artist_names = artist_names or []
    cache_key = (song_name, tuple(artist_names))
    if use_cache and cache_key in _CACHE:
        return _CACHE[cache_key]

    result: Optional[Preview] = None
    for provider in (_try_itunes, _try_deezer):
        try:
            result = provider(song_name, artist_names, timeout)
        except (requests.RequestException, ValueError):
            # ValueError covers JSON decode failures. Fall through to the next provider.
            result = None
        if result is not None:
            break

    if use_cache:
        _CACHE[cache_key] = result
    return result


def clear_cache() -> None:
    """Clear the in-process preview cache (mainly for tests)."""
    _CACHE.clear()
