"""
U3 — Offline artist-photo pre-bake (plan 2026-07-09-001, KTD4).

The public launch cannot afford live per-visitor photo resolution: the cache
is ~empty (19/119,729 resolved as of this plan) and every uncached artist
would hammer Wikidata/TheAudioDB/Deezer on first view. This script sweeps the
whole graph once, offline, using a BULK-OPTIMIZED source order that differs
from the live request path's (src/artist_photo.py's `resolve()`):

    1. Wikidata SPARQL, batched (~200-400 MBIDs per query) — cheap and exact.
    2. Deezer, per-artist — the dominant bulk workhorse (fast, good coverage,
       exact-name guard already prevents wrong faces).
    3. TheAudioDB, per-artist — reserved for the small remaining tail, since
       its free test key is capped at ~30 req/min and would take days over
       the full graph.

This inverts the live path's Wikidata->TheAudioDB->Deezer order deliberately
(KTD4): once everything is pre-baked, the live order never matters again.

Resumability + rate hygiene (same idiom as popularity_enrich.py /
spotify_enrich.py): `photo_url IS NULL` is the resume marker (checked via
get_unphotographed_artists); a rate-limit response (429, detected across the
three heterogeneous fetchers) aborts the WHOLE run cleanly — rows touched so
far stay persisted, everything else stays NULL for a later resume. Only after
an artist has been consulted by all three tiers with no error anywhere is it
marked the "none" sentinel (genuinely no photo, never re-queried).

CLI:
    python3 src/photo_prebake.py --db data/collaboration_network_mb.db
    python3 src/photo_prebake.py --db <db> --min-degree 3     # bound to prominent artists
    python3 src/photo_prebake.py --db <db> --limit 500        # measure a first pass
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from database import CollaborationDatabase, PHOTO_NONE_SENTINEL  # noqa: E402
from artist_photo import (  # noqa: E402
    resolve_deezer_single,
    resolve_theaudiodb_single,
    resolve_wikidata_batch,
)

CHUNK = 200  # commit progress every N artists (bounds loss on interrupt)
DEFAULT_TIMEOUT = 6.0
WIKIDATA_CHUNK_SIZE = 300  # MBIDs per SPARQL VALUES query (KTD4: ~200-400)
DEFAULT_WIKIDATA_RATE = 1.5  # requests/sec across chunks
DEFAULT_DEEZER_RATE = 8.0
DEFAULT_THEAUDIODB_RATE = 0.4  # ~24/min, safely under the ~30/min test-key ceiling


def _is_rate_limited(exc: Exception) -> bool:
    """Best-effort 429 detection across three heterogeneous fetchers:
    Deezer/TheAudioDB raise requests.HTTPError with a real status code via
    raise_for_status(); artist_photo's Wikidata fetch raises a generic
    RequestException with a distinguishing message (it checks the status
    code itself before raise_for_status can attach one)."""
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    return "429" in str(exc)


def _chunked(items: List, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def prebake(
    db: CollaborationDatabase,
    *,
    min_degree: int = 0,
    limit: Optional[int] = None,
    wikidata_rate: float = DEFAULT_WIKIDATA_RATE,
    deezer_rate: float = DEFAULT_DEEZER_RATE,
    theaudiodb_rate: float = DEFAULT_THEAUDIODB_RATE,
    timeout: float = DEFAULT_TIMEOUT,
    wikidata_chunk_size: int = WIKIDATA_CHUNK_SIZE,
    artist_ids: Optional[List[str]] = None,
    log=print,
) -> Dict[str, int]:
    """
    Run all three stages over every artist with photo_url IS NULL. Returns a
    summary dict: {'candidates', 'wikidata_hits', 'deezer_hits',
    'theaudiodb_hits', 'none_sentinel', 'errors', 'aborted'}.

    `artist_ids`, when given, force-resolves exactly this set (e.g. a
    showcase demo's chain hops, plan 2026-07-09-001, U5) instead of the
    normal popularity-priority queue.
    """
    candidates = db.get_unphotographed_artists(min_degree=min_degree, limit=limit,
                                               artist_ids=artist_ids)
    candidate_ids = [c["id"] for c in candidates]
    names_by_id = {c["id"]: c["name"] for c in candidates}

    resolved: Dict[str, str] = {}
    error_ids: Set[str] = set()
    aborted = False

    stage_hits = {"wikidata": 0, "deezer": 0, "theaudiodb": 0}
    write_batch: List[Tuple[str, str]] = []

    def flush():
        if write_batch:
            db.set_photo_urls_bulk(write_batch)
            write_batch.clear()

    def _pace(rate: float):
        if rate and rate > 0:
            time.sleep(1.0 / rate)

    # --- Stage 1: Wikidata, batched -------------------------------------------
    remaining = [aid for aid in candidate_ids if aid not in resolved]
    for chunk in _chunked(remaining, wikidata_chunk_size):
        try:
            hits = resolve_wikidata_batch(chunk, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — any fetch failure degrades this chunk
            if _is_rate_limited(exc):
                aborted = True
                log(f"  429 rate limit (Wikidata) — aborting cleanly; "
                    f"{len(resolved)} resolved so far, rest left for resume.")
                break
            error_ids.update(chunk)
            continue
        for mbid, url in hits.items():
            resolved[mbid] = url
            write_batch.append((mbid, url))
            stage_hits["wikidata"] += 1
        if len(write_batch) >= CHUNK:
            flush()
            log(f"  ...wikidata: {stage_hits['wikidata']} hits so far")
        _pace(wikidata_rate)
    flush()

    # --- Stage 2: Deezer, per-artist (bulk workhorse) -------------------------
    if not aborted:
        remaining = [aid for aid in candidate_ids if aid not in resolved]
        for aid in remaining:
            try:
                url = resolve_deezer_single(names_by_id[aid], timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                if _is_rate_limited(exc):
                    aborted = True
                    log(f"  429 rate limit (Deezer) — aborting cleanly; "
                        f"{len(resolved)} resolved so far, rest left for resume.")
                    break
                error_ids.add(aid)
                _pace(deezer_rate)
                continue
            if url:
                resolved[aid] = url
                write_batch.append((aid, url))
                stage_hits["deezer"] += 1
                if len(write_batch) >= CHUNK:
                    flush()
                    log(f"  ...deezer: {stage_hits['deezer']} hits so far")
            _pace(deezer_rate)
        flush()

    # --- Stage 3: TheAudioDB, per-artist (small remaining tail) ---------------
    if not aborted:
        remaining = [aid for aid in candidate_ids if aid not in resolved and aid not in error_ids]
        for aid in remaining:
            try:
                url = resolve_theaudiodb_single(aid, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                if _is_rate_limited(exc):
                    aborted = True
                    log(f"  429 rate limit (TheAudioDB) — aborting cleanly; "
                        f"{len(resolved)} resolved so far, rest left for resume.")
                    break
                error_ids.add(aid)
                _pace(theaudiodb_rate)
                continue
            if url:
                resolved[aid] = url
                write_batch.append((aid, url))
                stage_hits["theaudiodb"] += 1
                if len(write_batch) >= CHUNK:
                    flush()
                    log(f"  ...theaudiodb: {stage_hits['theaudiodb']} hits so far")
            _pace(theaudiodb_rate)
        flush()

    # --- Assemble the tri-state: everyone consulted by all 3 tiers with no
    # error anywhere and no URL is a genuine, permanent miss. ------------------
    none_sentinel = 0
    if not aborted:
        sentinel_batch = [
            (aid, PHOTO_NONE_SENTINEL)
            for aid in candidate_ids
            if aid not in resolved and aid not in error_ids
        ]
        if sentinel_batch:
            db.set_photo_urls_bulk(sentinel_batch)
            none_sentinel = len(sentinel_batch)

    return {
        "candidates": len(candidates),
        "wikidata_hits": stage_hits["wikidata"],
        "deezer_hits": stage_hits["deezer"],
        "theaudiodb_hits": stage_hits["theaudiodb"],
        "none_sentinel": none_sentinel,
        "errors": len(error_ids),
        "aborted": 1 if aborted else 0,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-bake artist photos (Wikidata batch -> Deezer -> TheAudioDB tail).")
    parser.add_argument("--db", required=True, help="Path to the built SQLite DB.")
    parser.add_argument("--min-degree", type=int, default=0,
                        help="Only resolve artists with degree >= N (bounds runtime).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap the number of candidate artists this run (measure a pass).")
    parser.add_argument("--wikidata-rate", type=float, default=DEFAULT_WIKIDATA_RATE)
    parser.add_argument("--deezer-rate", type=float, default=DEFAULT_DEEZER_RATE)
    parser.add_argument("--theaudiodb-rate", type=float, default=DEFAULT_THEAUDIODB_RATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--seed-ids", default=None,
                        help="Comma-separated artist ids to force-resolve "
                             "(e.g. a demo's showcase chain hops), ignoring "
                             "--min-degree and the popularity-priority queue.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: DB not found at {db_path}", file=sys.stderr)
        return 1

    seed_ids = [s.strip() for s in args.seed_ids.split(",") if s.strip()] if args.seed_ids else None

    db = CollaborationDatabase(str(db_path))
    to_do = len(db.get_unphotographed_artists(min_degree=args.min_degree, limit=args.limit,
                                              artist_ids=seed_ids))
    print(f"Pre-baking photos for up to {to_do} unresolved artists "
          f"(min_degree={args.min_degree}, limit={args.limit}, "
          f"seeded={bool(seed_ids)})...")

    summary = prebake(
        db, min_degree=args.min_degree, limit=args.limit,
        wikidata_rate=args.wikidata_rate, deezer_rate=args.deezer_rate,
        theaudiodb_rate=args.theaudiodb_rate, timeout=args.timeout,
        artist_ids=seed_ids,
    )

    print("Done." if not summary["aborted"] else "Aborted (rate limit).")
    print(f"  candidates:       {summary['candidates']:>8}")
    print(f"  wikidata hits:    {summary['wikidata_hits']:>8}")
    print(f"  deezer hits:      {summary['deezer_hits']:>8}")
    print(f"  theaudiodb hits:  {summary['theaudiodb_hits']:>8}")
    print(f"  none (exhausted): {summary['none_sentinel']:>8}")
    print(f"  errors (retry):   {summary['errors']:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
