"""
Artist-photo coverage waterfall (plan 2026-07-06-010, U1).

Resolves a good-quality artist photo for a set of artists from the first source
that has one, MBID-exact before name-matched, so the six-degrees chain rarely
looks empty:

  1. Wikidata `P18` -> Commons `Special:FilePath`  (batched by MBID, exact)
  2. TheAudioDB `artist-mb.php?i=<mbid>`            (per MBID, exact)
  3. Deezer `search/artist?q=<name>`                (per name, EXACT-name guard)

Design notes (mirrors the plan-008 preview resolver discipline):
- Tri-state per artist so persistence can tell "genuinely no photo" from "retry
  later": a validated URL, `NO_PHOTO` (every source was consulted and none hit
  -> caller persists the "none" sentinel) or `UNAVAILABLE` (a source errored /
  timed out before the waterfall completed -> caller leaves the row NULL so a
  transient failure retries on a later request).
- The Deezer tier matches by *name*, so it MUST pass an EXACT normalized-name
  match (reusing `preview_fetcher._normalize`) — NOT the bidirectional-substring
  `_artist_matches`, which was built for finding a connecting artist inside a
  track's combined credit string and would accept containment collisions like
  "June" -> "Larry June". A wrong face is worse than the fallback.
- Every candidate URL is validated (well-formed https on a known-host allowlist)
  before it is returned, so a malformed or unexpected value from a third party is
  never persisted and rendered.
- Never raises: any source failure is swallowed and downgrades that artist to
  `UNAVAILABLE`, so the connection endpoint always responds.
- Injectable per-source fetch seams keep the whole waterfall unit-testable with
  no network.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from preview_fetcher import _normalize

# Tri-state sentinels. Distinct from any real URL so the caller can branch on
# identity. NO_PHOTO -> persist the "none" sentinel (never re-query);
# UNAVAILABLE -> leave the row NULL (retry on a later request).
NO_PHOTO = "NO_PHOTO"
UNAVAILABLE = "UNAVAILABLE"

# Conservative per-request timeout — a slow third party must never hang a render
# (same lesson as preview_fetcher.DEFAULT_TIMEOUT).
DEFAULT_TIMEOUT = 5.0

# Total wall-clock budget for resolving one connection's artists. Once exceeded,
# still-unresolved artists come back UNAVAILABLE (left NULL) and resolve on a
# later request, so a slow-upstream day can't hold the connection response for
# tens of seconds.
DEFAULT_BUDGET_S = 3.0

# Commons thumbnail width (Special:FilePath accepts ?width=N -> 302 to a sized
# image). ~320px is crisp for a chain avatar without shipping the full original.
COMMONS_WIDTH = 320

_USER_AGENT = "RabbitHole/0.1 (jorsanto@umich.edu)"

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
# TheAudioDB's public test key (free, rate-limited, intended for dev/demo).
# Env-overridable; production keys are Patreon-gated and out of scope with the
# other deferred scale work.
THEAUDIODB_KEY = os.environ.get("THEAUDIODB_KEY", "2")
DEEZER_ARTIST_SEARCH_URL = "https://api.deezer.com/search/artist"

# Only persist/serve image URLs from these hosts. Anything else (a redirect to a
# tracker, a javascript:/data: URI, an unexpected CDN) is treated as a miss.
_ALLOWED_HOST_SUFFIXES = (
    "wikimedia.org",   # commons.wikimedia.org, upload.wikimedia.org
    "theaudiodb.com",  # r2.theaudiodb.com, www.theaudiodb.com
    "dzcdn.net",       # e-cdns-images.dzcdn.net (Deezer image CDN)
)


def _validate_url(url: Optional[str]) -> Optional[str]:
    """Return `url` iff it is a well-formed https:// URL on the host allowlist,
    else None. This is the trust boundary: a value that fails here is never
    persisted or rendered (KTD2 — persisted URLs are served to every visitor)."""
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if not any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES):
        return None
    return url.strip()


def _name_matches(query_name: str, candidate_name: Optional[str]) -> bool:
    """EXACT normalized-name equality (reusing preview_fetcher._normalize).
    Deliberately stricter than `_artist_matches` — photo identity is one-to-one,
    so a substring/containment match ("June" vs "Larry June") is a wrong face."""
    if not candidate_name:
        return False
    return _normalize(query_name) == _normalize(candidate_name)


def _commons_thumb(image_url: str, width: int = COMMONS_WIDTH) -> str:
    """Normalize a Wikidata P18 value to an https Commons Special:FilePath URL
    with a width hint (WDQS often returns the http form)."""
    if image_url.startswith("http://"):
        image_url = "https://" + image_url[len("http://"):]
    sep = "&" if "?" in image_url else "?"
    return f"{image_url}{sep}width={width}"


# --- Per-source fetchers (injectable seams; each returns hits, never raises to
#     the caller in the batched Wikidata case is handled by resolve()) ---------

def _wikidata_batch(mbids: List[str], timeout: float) -> Dict[str, str]:
    """One SPARQL query mapping P434 (MBID) -> P18 (image) for all `mbids`.
    Returns {mbid: commons_thumb_url} for the artists that have an image; MBIDs
    with no P18 simply don't appear. Raises on network/parse error (resolve()
    catches it and marks those artists UNAVAILABLE for that tier)."""
    if not mbids:
        return {}
    values = " ".join(f'"{m}"' for m in mbids)
    query = (
        "SELECT ?mbid ?image WHERE { "
        f"VALUES ?mbid {{ {values} }} "
        "?item wdt:P434 ?mbid . "
        "?item wdt:P18 ?image . }"
    )
    resp = requests.get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/sparql-results+json"},
    )
    if resp.status_code == 429:
        # Honor WDQS rate limiting — treat as a tier failure (retryable later).
        raise requests.RequestException("Wikidata 429")
    resp.raise_for_status()
    bindings = resp.json().get("results", {}).get("bindings", [])
    out: Dict[str, str] = {}
    for b in bindings:
        mbid = b.get("mbid", {}).get("value")
        image = b.get("image", {}).get("value")
        if mbid and image and mbid not in out:
            out[mbid] = _commons_thumb(image)
    return out


def _theaudiodb_by_mbid(mbid: str, timeout: float) -> Optional[str]:
    """TheAudioDB artist-mb.php?i=<mbid> -> strArtistThumb (one call per MBID,
    MBID-exact). Returns the thumb URL or None. Raises on network/parse error."""
    url = f"https://www.theaudiodb.com/api/v1/json/{THEAUDIODB_KEY}/artist-mb.php"
    resp = requests.get(
        url, params={"i": mbid}, timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    artists = resp.json().get("artists")
    if not artists:
        return None
    thumb = artists[0].get("strArtistThumb")
    return thumb or None


def _deezer_by_name(name: str, timeout: float) -> Optional[Tuple[str, str]]:
    """Deezer search/artist?q=<name> -> (returned_name, picture_xl) for the top
    hit, or None. The caller applies the EXACT-name guard; this only fetches.
    Raises on network/parse error."""
    resp = requests.get(
        DEEZER_ARTIST_SEARCH_URL, params={"q": name, "limit": 1}, timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return None
    top = data[0]
    picture = top.get("picture_xl") or top.get("picture_big")
    returned_name = top.get("name")
    if not picture:
        return None
    return (returned_name or "", picture)


# --- Stage-scoped seams for the offline pre-bake (plan 2026-07-09-001, U3) --
#
# resolve() above is tuned for the LIVE request path: budgeted, single call,
# fixed Wikidata->TheAudioDB->Deezer order, silently degrades every failure to
# UNAVAILABLE. The offline pre-bake needs the OPPOSITE shape (KTD4): each tier
# run to completion across the whole graph with its own pacing, Deezer before
# TheAudioDB (Deezer is the bulk workhorse; TheAudioDB's 30/min test key is
# reserved for the small remaining tail), and callers that want to see and
# react to exceptions (rate-limit abort) rather than have them swallowed. These
# thin wrappers reuse the exact same fetchers, validation, and name-match
# guard as resolve() so both paths agree on what counts as a hit.

def resolve_wikidata_batch(
    mbids: List[str], *, timeout: float = DEFAULT_TIMEOUT,
    wikidata_fetch: Callable[[List[str], float], Dict[str, str]] = _wikidata_batch,
) -> Dict[str, str]:
    """One Wikidata batch call -> {mbid: validated_url} for the MBIDs that had
    an image. MBIDs with no P18 are simply absent (a clean miss, not an
    error). Raises the fetch's exception straight through (network/HTTP/429)
    so a batch driver can decide whether to retry the chunk or abort the run."""
    hits = wikidata_fetch(mbids, timeout)
    out: Dict[str, str] = {}
    for mbid, url in hits.items():
        valid = _validate_url(url)
        if valid:
            out[mbid] = valid
    return out


def resolve_deezer_single(
    name: str, *, timeout: float = DEFAULT_TIMEOUT,
    deezer_fetch: Callable[[str, float], Optional[Tuple[str, str]]] = _deezer_by_name,
) -> Optional[str]:
    """Deezer-only lookup for one artist by name: a validated photo URL if the
    top hit passes the exact-name guard, else None (a clean miss). Raises the
    fetch's exception straight through."""
    cand = deezer_fetch(name, timeout)
    if cand is None:
        return None
    returned_name, picture = cand
    if _name_matches(name, returned_name):
        return _validate_url(picture)
    return None


def resolve_theaudiodb_single(
    mbid: str, *, timeout: float = DEFAULT_TIMEOUT,
    theaudiodb_fetch: Callable[[str, float], Optional[str]] = _theaudiodb_by_mbid,
) -> Optional[str]:
    """TheAudioDB-only lookup for one artist by MBID: a validated photo URL or
    None (a clean miss). Raises the fetch's exception straight through."""
    thumb = theaudiodb_fetch(mbid, timeout)
    return _validate_url(thumb)


def resolve(
    artists: List[Tuple[str, str]],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    budget_s: Optional[float] = DEFAULT_BUDGET_S,
    wikidata_fetch: Callable[[List[str], float], Dict[str, str]] = _wikidata_batch,
    theaudiodb_fetch: Callable[[str, float], Optional[str]] = _theaudiodb_by_mbid,
    deezer_fetch: Callable[[str, float], Optional[Tuple[str, str]]] = _deezer_by_name,
) -> Dict[str, str]:
    """Resolve photos for `artists` (a list of (mbid, name)).

    Returns {mbid: result} where result is a validated https URL, `NO_PHOTO`
    (every source consulted, none hit), or `UNAVAILABLE` (a source errored /
    timed out, or the budget ran out before this artist was resolved). The
    caller persists a URL, persists the "none" sentinel for NO_PHOTO, and leaves
    the row NULL for UNAVAILABLE.

    The per-source fetch seams are injectable so the waterfall is fully testable
    offline. Never raises.
    """
    resolved: Dict[str, str] = {}
    errored: Dict[str, bool] = {mbid: False for mbid, _ in artists}
    deadline = (time.monotonic() + budget_s) if budget_s is not None else None

    def _out_of_budget() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    # --- Tier 1: Wikidata batch (MBID-exact) ---------------------------------
    mbids = [mbid for mbid, _ in artists]
    if mbids and not _out_of_budget():
        try:
            hits = wikidata_fetch(mbids, timeout)
        except (requests.RequestException, ValueError):
            for mbid in mbids:
                errored[mbid] = True
            hits = {}
        for mbid, url in hits.items():
            valid = _validate_url(url)
            if valid:
                resolved[mbid] = valid
    elif mbids:
        # No Wikidata attempt at all (budget) — every artist is still retryable.
        for mbid in mbids:
            errored[mbid] = True

    # --- Tier 2: TheAudioDB by MBID (MBID-exact) -----------------------------
    for mbid, _name in artists:
        if mbid in resolved:
            continue
        if _out_of_budget():
            errored[mbid] = True
            continue
        try:
            thumb = theaudiodb_fetch(mbid, timeout)
        except (requests.RequestException, ValueError):
            errored[mbid] = True
            continue
        valid = _validate_url(thumb)
        if valid:
            resolved[mbid] = valid

    # --- Tier 3: Deezer by name (EXACT-name guard) ---------------------------
    for mbid, name in artists:
        if mbid in resolved:
            continue
        if _out_of_budget():
            errored[mbid] = True
            continue
        try:
            cand = deezer_fetch(name, timeout)
        except (requests.RequestException, ValueError):
            errored[mbid] = True
            continue
        if cand is None:
            continue
        returned_name, picture = cand
        if _name_matches(name, returned_name):
            valid = _validate_url(picture)
            if valid:
                resolved[mbid] = valid
        # A name mismatch is a definitive miss for this tier (no wrong face);
        # it does NOT set errored — we consulted Deezer and it had no match.

    # --- Assemble the tri-state ----------------------------------------------
    results: Dict[str, str] = {}
    for mbid, _name in artists:
        if mbid in resolved:
            results[mbid] = resolved[mbid]
        elif errored[mbid]:
            results[mbid] = UNAVAILABLE
        else:
            results[mbid] = NO_PHOTO
    return results
