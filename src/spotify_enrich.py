"""
Build-time Spotify track-id enrichment (plan 2026-07-06-004, U1).

Resolves each connecting song's Spotify track id ONCE, offline, and persists it
on `songs.spotify_track_id`. The running app then reads the stored id and renders
Spotify's embed player — it never calls Spotify's API per render, so there is no
rate-limit exposure at demo scale (R2, KTD2). This is the same bounded, resumable,
one-time pattern as the popularity pass (src/popularity_enrich.py).

Why the embed at all (KTD1): Spotify deprecated `preview_url` for dev-mode apps,
and iTunes/Deezer miss real songs ("Slow Down" — Friday/Mariah the Scientist).
The embed iframe plays a 30s preview for logged-out visitors via the track id
alone, bypassing the dead `preview_url` — so resolving the id is all we need.

Match quality (KTD2 / Risk): we reuse preview_fetcher's title+artist accept-logic
and store a track id ONLY when the top hits pass it. A wrong-but-plausible id
would play the wrong song, so on any miss we store the "none" sentinel rather
than a loose match — the UI degrades to no player.

Resumability + rate hygiene (the project's known sore spot — cf. the retired
Spotify crawl): NULL means "not yet checked"; a real id or the "none" sentinel
means "checked". A re-run only touches NULL rows, so a second full run makes zero
search calls. Conservative pacing; a 429 aborts the run cleanly (rows stay NULL
for the next resume) honoring Retry-After; any other network/parse error leaves
that one song for retry and never crashes the run.

CLI:
    python3 src/spotify_enrich.py --db data/collaboration_network_mb.db
    python3 src/spotify_enrich.py --db <db> --min-degree 3   # bound to prominent edges
    python3 src/spotify_enrich.py --db <db> --limit 500      # measure a first pass
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from database import CollaborationDatabase, NO_TRACK_SENTINEL  # noqa: E402
from preview_fetcher import _accept  # noqa: E402  (reuse title+artist accept-logic)

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 (public endpoint)
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
DEFAULT_TIMEOUT = 6.0
DEFAULT_RATE = 8.0  # requests/sec ceiling (plan: ~5-10)
CHUNK = 200  # commit progress every N songs (bounds loss on interrupt)
SEARCH_LIMIT = 5  # candidates per query (mirror preview_fetcher)

_USER_AGENT = "RabbitHole/0.1 (jorsanto@umich.edu)"


class RateLimited(Exception):
    """Raised on an HTTP 429 so the run can abort cleanly (leaving rows NULL for
    a later resume) instead of hammering the API."""

    def __init__(self, retry_after: Optional[float] = None):
        super().__init__("Spotify rate limit (429)")
        self.retry_after = retry_after


def get_client_token(client_id: str, client_secret: str,
                     timeout: float = DEFAULT_TIMEOUT) -> str:
    """Fetch a client-credentials access token (no user auth — the app's own
    keys). Raises on network/HTTP error."""
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {auth}",
                 "User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_track(query: str, token: str,
                 timeout: float = DEFAULT_TIMEOUT) -> List[dict]:
    """
    Return raw Spotify track candidates for a query (each: {'id', 'name',
    'artists': [{'name'}...]}). Raises RateLimited on 429 (honoring Retry-After)
    so the caller aborts; raises requests.RequestException / ValueError on other
    failures so the caller can leave that song for retry.
    """
    resp = requests.get(
        SPOTIFY_SEARCH_URL,
        params={"q": query, "type": "track", "limit": SEARCH_LIMIT},
        headers={"Authorization": f"Bearer {token}",
                 "User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After")
        raise RateLimited(float(retry) if retry else None)
    resp.raise_for_status()
    return resp.json().get("tracks", {}).get("items", [])


def _build_query(song_name: str, artist_names: List[str]) -> str:
    artists = " ".join(a for a in artist_names if a)
    return f"{song_name} {artists}".strip()


def _accept_track(song_name: str, artist_names: List[str], track: dict) -> bool:
    """Apply preview_fetcher's title+artist accept-logic to a Spotify track."""
    artist_field = ", ".join(a.get("name", "") for a in track.get("artists", []))
    return _accept(song_name, artist_names, track.get("name", ""), artist_field)


def _resolve_track_id(song_name: str, artist_names: List[str],
                      candidates: List[dict]) -> str:
    """Return the first candidate's id that passes accept-logic, else the
    NO_TRACK_SENTINEL. A wrong id is worse than none (KTD2)."""
    for track in candidates:
        tid = track.get("id")
        if tid and _accept_track(song_name, artist_names, track):
            return tid
    return NO_TRACK_SENTINEL


def enrich(
    db: CollaborationDatabase,
    token: Optional[str] = None,
    min_degree: int = 0,
    limit: Optional[int] = None,
    rate: float = DEFAULT_RATE,
    timeout: float = DEFAULT_TIMEOUT,
    search: Callable[[str, str, float], List[dict]] = search_track,
    log: Callable[[str], None] = print,
) -> Dict[str, int]:
    """
    Resolve and persist Spotify track ids for unresolved songs. Returns a summary
    dict: {'processed', 'resolved', 'sentinel', 'errors', 'aborted'}.

    'resolved' = stored a real track id; 'sentinel' = stored "none" (searched, no
    acceptable match); 'errors' = transient failures left NULL for retry;
    'aborted' = 1 if a 429 stopped the run early.
    """
    songs = db.get_songs_without_track_id(min_degree=min_degree, limit=limit)
    min_interval = (1.0 / rate) if rate and rate > 0 else 0.0

    processed = resolved = sentinel = errors = aborted = 0
    batch: List[Tuple[int, str]] = []

    def flush():
        if batch:
            db.set_spotify_track_id_bulk(batch)
            batch.clear()

    for song in songs:
        query = _build_query(song["song_name"], song["collaborators"])
        try:
            candidates = search(query, token, timeout)
        except RateLimited as rl:
            aborted = 1
            wait = f" (Retry-After: {rl.retry_after}s)" if rl.retry_after else ""
            log(f"  429 rate limit — aborting cleanly{wait}; "
                f"{processed} done, rest left NULL for resume.")
            break
        except (requests.RequestException, ValueError):
            # Transient: leave this song NULL so a later run retries it.
            errors += 1
            if min_interval:
                time.sleep(min_interval)
            continue

        track_id = _resolve_track_id(song["song_name"], song["collaborators"], candidates)
        if track_id == NO_TRACK_SENTINEL:
            sentinel += 1
        else:
            resolved += 1
        batch.append((song["id"], track_id))
        processed += 1

        if len(batch) >= CHUNK:
            flush()
            log(f"  ...{processed} processed ({resolved} resolved, {sentinel} none)")
        if min_interval:
            time.sleep(min_interval)

    flush()
    return {
        "processed": processed,
        "resolved": resolved,
        "sentinel": sentinel,
        "errors": errors,
        "aborted": aborted,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve + persist Spotify track ids for connecting songs.")
    parser.add_argument("--db", required=True, help="Path to the built SQLite DB.")
    parser.add_argument("--min-degree", type=int, default=0,
                        help="Only songs on an edge touching an artist with "
                             "degree >= N (bounds runtime).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap the number of songs this run (measure a pass).")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE,
                        help="Max Spotify search requests/sec.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: DB not found at {db_path}", file=sys.stderr)
        return 1

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("error: SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not set "
              "(see .env.example).", file=sys.stderr)
        return 1

    try:
        token = get_client_token(client_id, client_secret, timeout=args.timeout)
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"error: could not obtain a Spotify token: {exc}", file=sys.stderr)
        return 1

    db = CollaborationDatabase(str(db_path))
    to_do = len(db.get_songs_without_track_id(min_degree=args.min_degree, limit=args.limit))
    print(f"Resolving Spotify track ids for up to {to_do} unresolved songs "
          f"(min_degree={args.min_degree}, limit={args.limit})...")

    summary = enrich(db, token=token, min_degree=args.min_degree, limit=args.limit,
                     rate=args.rate, timeout=args.timeout)

    print("Done." if not summary["aborted"] else "Aborted (rate limit).")
    print(f"  processed:  {summary['processed']}")
    print(f"  resolved:   {summary['resolved']:>8}")
    print(f"  none (miss):{summary['sentinel']:>8}")
    print(f"  errors:     {summary['errors']:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
