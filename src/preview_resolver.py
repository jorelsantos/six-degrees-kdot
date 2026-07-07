"""
Preview waterfall resolver (plan 008, U2).

Returns the best directly-playable 30s preview for a (title, artists) pair from
the first source that has one, so the UI can play a uniform in-app <audio>
player and only ever show songs with a confirmed preview (no dead buttons):

  1. Spotify embed audioPreview.url  (via spotify_preview; needs a track id)
  2. iTunes previewUrl               (preview_fetcher._try_itunes; sanctioned)
  3. Deezer preview                  (preview_fetcher._try_deezer)

Every tier reuses preview_fetcher's title+artist accept-logic so a wrong track
is never returned. Never raises — a miss returns None and the caller degrades
to the Apple Music search link (apple_search_url).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional
from urllib.parse import quote_plus

import requests

import preview_fetcher
import spotify_preview

DEFAULT_TIMEOUT = 6.0


@dataclass(frozen=True)
class ResolvedPreview:
    source: str                       # 'spotify' | 'itunes' | 'deezer'
    audio_url: str                    # directly-playable mp3/m4a
    artwork_url: Optional[str] = None
    matched_title: Optional[str] = None
    matched_artist: Optional[str] = None
    store_url: Optional[str] = None   # link to the full track on that service


def _spotify_tier(
    title: str,
    artists: List[str],
    spotify_track_id: Optional[str],
    scrape: Callable[[str], Optional[dict]],
) -> Optional[ResolvedPreview]:
    tid = spotify_track_id
    if not tid or tid == "none":  # NULL / unresolved / "none" sentinel
        return None
    data = scrape(tid)
    if not data or not data.get("audio_url"):
        return None
    return ResolvedPreview(
        source="spotify",
        audio_url=data["audio_url"],
        artwork_url=data.get("artwork_url"),
        matched_title=title,
        matched_artist=artists[0] if artists else None,
        store_url=f"https://open.spotify.com/track/{tid}",
    )


def _fetcher_tier(source: str, fn, title: str, artists: List[str],
                  timeout: float) -> Optional[ResolvedPreview]:
    """Adapt a preview_fetcher provider (_try_itunes/_try_deezer) to a
    ResolvedPreview. Swallows network/parse errors → None."""
    try:
        p = fn(title, artists, timeout)
    except (requests.RequestException, ValueError):
        return None
    if p is None:
        return None
    return ResolvedPreview(
        source=source,
        audio_url=p.preview_url,
        artwork_url=None,
        matched_title=p.matched_title,
        matched_artist=p.matched_artist,
        store_url=p.store_url,
    )


def resolve_preview(
    title: str,
    artists: Optional[List[str]] = None,
    spotify_track_id: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    scrape: Callable[[str], Optional[dict]] = spotify_preview.scrape_preview,
    itunes=preview_fetcher._try_itunes,
    deezer=preview_fetcher._try_deezer,
) -> Optional[ResolvedPreview]:
    """
    Walk the waterfall; return the first playable preview or None. Injectable
    source seams (scrape/itunes/deezer) keep this fully unit-testable offline.
    """
    artists = artists or []

    sp = _spotify_tier(title, artists, spotify_track_id, scrape)
    if sp is not None:
        return sp

    it = _fetcher_tier("itunes", itunes, title, artists, timeout)
    if it is not None:
        return it

    dz = _fetcher_tier("deezer", deezer, title, artists, timeout)
    if dz is not None:
        return dz

    return None


def apple_search_url(title: str, artist: str = "") -> str:
    """The R5 last-resort fallback: an Apple Music search for the track."""
    term = f"{title} {artist}".strip()
    return f"https://music.apple.com/us/search?term={quote_plus(term)}"
