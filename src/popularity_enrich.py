"""
U1 — Popularity enrichment for the MusicBrainz collaboration graph.

Every artist in a freshly-built MB DB has popularity = 0 (MusicBrainz has no
popularity metric), so the app's `ORDER BY popularity DESC` is a no-op and search
falls back to alphabetical — "Mariah" surfaces obscure Mariahs above Mariah
Carey. This pass backfills a real prominence signal into the existing
`popularity` column so ranking works.

Signal (KTD1):
- Primary: Last.fm `artist.getInfo` keyed by MBID. Our nodes ARE MBIDs
  (musicbrainz_ingest keys on artist.gid, KTD7), so the lookup needs no
  name-matching guesswork. We store the `listeners` count as popularity.
- Fallback: an artist's graph-degree (collaboration count) whenever Last.fm has
  no match, errors, or no API key is configured. Degree alone already fixes the
  headline ranking bug (Mariah Carey has ~192 edges vs 1-2 for obscure Mariahs);
  Last.fm refines fidelity among genuinely-collaborative artists.

Design (KTD2):
- Standalone, re-runnable, and decoupled from the dump-parsing build.
- Resumable: a `pop_enriched` marker column distinguishes "checked" from the
  ambiguous popularity=0; already-enriched artists are skipped on re-run, and
  progress is committed in chunks so an interrupt loses at most one chunk.
- Rate-limit hygiene (the project's known sore spot — see the retired Spotify
  crawl and docs/plans/2026-07-01-002): conservative pacing + timeout, and every
  network/parse failure degrades to the degree fallback rather than crashing.
- `--min-degree N` bounds runtime by enriching only artists with degree >= N
  (the ambiguous-collision set), leaving graph-degree to order the long tail.

CLI:
    python3 src/popularity_enrich.py --db data/collaboration_network_mb.db
    python3 src/popularity_enrich.py --db <db> --min-degree 3   # fast pass
    LASTFM_API_KEY=... python3 src/popularity_enrich.py --db <db>
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from database import CollaborationDatabase  # noqa: E402

LASTFM_API_URL = "http://ws.audioscrobbler.com/2.0/"
DEFAULT_TIMEOUT = 6.0
DEFAULT_RATE = 5.0  # requests/sec ceiling for Last.fm
CHUNK = 200  # commit progress every N artists (bounds loss on interrupt)

_USER_AGENT = "RabbitHole/0.1 (jorsanto@umich.edu)"


def fetch_listeners(mbid: str, api_key: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[int]:
    """
    Return the Last.fm listener count for an artist by MBID, or None if the
    artist isn't found / the response lacks a usable stat. Raises on network or
    HTTP error so the caller can decide (it degrades to the degree fallback).
    """
    params = {
        "method": "artist.getinfo",
        "mbid": mbid,
        "api_key": api_key,
        "format": "json",
    }
    resp = requests.get(
        LASTFM_API_URL, params=params, timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:  # e.g. 6 = artist not found
        return None
    stats = (data.get("artist") or {}).get("stats") or {}
    listeners = stats.get("listeners")
    if listeners is None:
        return None
    try:
        return int(listeners)
    except (ValueError, TypeError):
        return None


def enrich(
    db: CollaborationDatabase,
    api_key: Optional[str] = None,
    min_degree: int = 0,
    rate: float = DEFAULT_RATE,
    timeout: float = DEFAULT_TIMEOUT,
    fetch: Callable[[str, str, float], Optional[int]] = fetch_listeners,
    log: Callable[[str], None] = print,
) -> Dict[str, int]:
    """
    Backfill the `popularity` column. Returns a summary dict:
      {'processed', 'lastfm', 'degree_fallback', 'skipped_below_min_degree'}.

    Without an api_key, every eligible artist gets its graph-degree — still a
    correct, if coarser, ranking signal.
    """
    degrees = db.get_all_degrees()
    artists = db.get_unenriched_artists()
    min_interval = (1.0 / rate) if rate and rate > 0 else 0.0

    processed = lastfm = degree_fallback = skipped = 0
    batch: List[tuple] = []

    def flush():
        if batch:
            db.set_popularity_bulk(batch)
            batch.clear()

    for art in artists:
        deg = degrees.get(art["id"], 0)
        if deg < min_degree:
            skipped += 1
            continue

        listeners: Optional[int] = None
        if api_key:
            try:
                listeners = fetch(art["id"], api_key, timeout)
            except (requests.RequestException, ValueError):
                listeners = None  # degrade to degree fallback; never crash the run
            if min_interval:
                time.sleep(min_interval)

        if listeners is not None:
            value = listeners
            lastfm += 1
        else:
            value = deg
            degree_fallback += 1

        batch.append((art["id"], value))
        processed += 1

        if len(batch) >= CHUNK:
            flush()
            log(f"  ...{processed} processed "
                f"({lastfm} Last.fm, {degree_fallback} degree-fallback)")

    flush()
    summary = {
        "processed": processed,
        "lastfm": lastfm,
        "degree_fallback": degree_fallback,
        "skipped_below_min_degree": skipped,
    }
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill artist popularity (Last.fm + degree).")
    parser.add_argument("--db", required=True, help="Path to the built SQLite DB.")
    parser.add_argument("--min-degree", type=int, default=0,
                        help="Only enrich artists with degree >= N (bounds runtime).")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE,
                        help="Max Last.fm requests/sec.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: DB not found at {db_path}", file=sys.stderr)
        return 1

    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        print("note: LASTFM_API_KEY not set — enriching with graph-degree only "
              "(still fixes ranking, just coarser).")

    db = CollaborationDatabase(str(db_path))
    to_do = len(db.get_unenriched_artists())
    print(f"Enriching popularity for up to {to_do} un-enriched artists "
          f"(min_degree={args.min_degree})...")

    summary = enrich(db, api_key=api_key, min_degree=args.min_degree,
                     rate=args.rate, timeout=args.timeout)

    print("Done.")
    print(f"  processed:        {summary['processed']}")
    print(f"  Last.fm listeners:{summary['lastfm']:>8}")
    print(f"  degree fallback:  {summary['degree_fallback']:>8}")
    print(f"  skipped (<min):   {summary['skipped_below_min_degree']:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
