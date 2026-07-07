"""
Spotify embed preview scraper (plan 008, U1 — GO'd by scripts/spotify_scrape_spike.py).

The Spotify Web API's `preview_url` is dead for dev apps, but the public embed
page `open.spotify.com/embed/track/{id}` still ships a `__NEXT_DATA__` JSON blob
containing `audioPreview.url` — a real, directly-playable 30s mp3 on p.scdn.co.
The spike measured 100% of resolved track ids yielding a preview, zero errors at
conservative pacing. This module is the hardened, single-track resolver.

Safe/minimal posture (KTD7): browser-like User-Agent, conservative timeout,
each track fetched at most once (in-process cache), graceful None on any
failure (never raises). Demo-scoped — public-traffic guardrails deferred.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import requests

EMBED_URL = "https://open.spotify.com/embed/track/{}"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)
DEFAULT_TIMEOUT = 8.0

# audioPreview.url is the playable mp3. Cover art lives on i.scdn.co (legacy) or
# image-cdn-*.spotifycdn.com (current); the id suffix encodes size — 00001e02 ≈
# 300px (crisp for a small thumb), 00004851 ≈ 64px, 0000b273 ≈ 640px.
_AUDIO_RE = re.compile(r'"audioPreview"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"')
_ART_RE = re.compile(
    r'https://(?:i\.scdn\.co|[a-z0-9-]+\.spotifycdn\.com)/image/[a-z0-9]+'
)


def _best_artwork(html: str) -> Optional[str]:
    """Pick a reasonably-sized cover-art URL from the embed, preferring the
    ~300px variant, else any match."""
    urls = _ART_RE.findall(html)
    if not urls:
        return None
    for u in urls:
        if "00001e02" in u:  # ~300px — ideal for a small thumbnail
            return u
    return urls[0]

# Process-lifetime cache keyed by track id. Values are {'audio_url','artwork_url'} | None.
_CACHE: dict = {}


def _default_fetch(track_id: str, timeout: float) -> Optional[str]:
    """Fetch the embed HTML, or None on non-200/network error."""
    resp = requests.get(
        EMBED_URL.format(track_id),
        headers={"User-Agent": _BROWSER_UA},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None
    return resp.text


def scrape_preview(
    track_id: str,
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    fetch: Callable[[str, float], Optional[str]] = _default_fetch,
) -> Optional[dict]:
    """
    Return {'audio_url': str, 'artwork_url': Optional[str]} for a Spotify track id,
    or None if the embed has no playable preview / any failure. Never raises.
    """
    if not track_id:
        return None
    if use_cache and track_id in _CACHE:
        return _CACHE[track_id]

    result: Optional[dict] = None
    try:
        html = fetch(track_id, timeout)
        if html and "__NEXT_DATA__" in html:
            m = _AUDIO_RE.search(html)
            if m and m.group(1) and m.group(1) != "null":
                result = {"audio_url": m.group(1), "artwork_url": _best_artwork(html)}
    except (requests.RequestException, ValueError):
        result = None

    if use_cache:
        _CACHE[track_id] = result
    return result


def clear_cache() -> None:
    """Clear the in-process cache (mainly for tests)."""
    _CACHE.clear()
