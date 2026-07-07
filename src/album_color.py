"""
Album cover → dominant color (plan 009, KTD2).

Extracts a representative color from a cover-art image server-side (Pillow) so
the preview card can theme itself like a Spotify card. Server-side (not client
canvas) keeps it uniform across every image CDN regardless of CORS.

Best-effort: any fetch/decode failure returns None (the card falls back to the
neutral surface). Cached per image URL — at page-load scale each cover is
processed once.
"""
from __future__ import annotations

from io import BytesIO
from typing import Callable, Optional

import requests
from PIL import Image

DEFAULT_TIMEOUT = 6.0
_BROWSER_UA = "RabbitHole/0.1 (jorsanto@umich.edu)"

# Process-lifetime cache: image URL -> "#rrggbb" | None.
_CACHE: dict = {}


def _default_fetch(url: str, timeout: float) -> Optional[bytes]:
    resp = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=timeout)
    if resp.status_code != 200:
        return None
    return resp.content


def dominant_color(
    image_url: Optional[str],
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    fetch: Callable[[str, float], Optional[bytes]] = _default_fetch,
) -> Optional[str]:
    """Return a representative '#rrggbb' for the cover, or None on any failure.
    Prefers a non-extreme (not near-black/near-white) color so the card gets a
    color, not a muddy gray, from a mostly-dark or mostly-light cover."""
    if not image_url:
        return None
    if use_cache and image_url in _CACHE:
        return _CACHE[image_url]

    color: Optional[str] = None
    try:
        data = fetch(image_url, timeout)
        if data:
            img = Image.open(BytesIO(data)).convert("RGB")
            img.thumbnail((64, 64))
            # Reduce to a small palette, then rank by frequency.
            quant = img.quantize(colors=8).convert("RGB")
            counts = quant.getcolors(64) or []
            counts.sort(reverse=True)  # (count, (r,g,b)) — most common first
            pick = None
            for _count, (r, g, b) in counts:
                if max(r, g, b) > 30 and min(r, g, b) < 230:  # skip near-black/white
                    pick = (r, g, b)
                    break
            if pick is None and counts:
                pick = counts[0][1]
            if pick is not None:
                color = "#%02x%02x%02x" % pick
    except (requests.RequestException, ValueError, OSError):
        color = None

    if use_cache:
        _CACHE[image_url] = color
    return color


def clear_cache() -> None:
    """Clear the in-process cache (mainly for tests)."""
    _CACHE.clear()
