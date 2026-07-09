"""
U4 — Offline Spotify track-ID pre-bake for path-tree connecting songs (plan
2026-07-09-001, KTD5).

The path-tree precompute (U2, src/path_tree.py) picked one representative
"via-song" per artist -> Kendrick edge. This script resolves each of those
via-songs to a real Spotify track id using the OFFICIAL Web API (client
credentials), so the public app can render Spotify's embed player straight
from stored ids at zero runtime cost (KTD3). Only the path tree's via-songs
matter here (<=119k, one per artist) — not the full 563k-song catalog, which
is what src/spotify_enrich.py's broader sweep is for.

Per-edge waterfall (adversarial review finding, U2/KTD3): a single pre-picked
song per edge would forfeit resolvability options a real collaboration edge
often has (an edge frequently has more than one song). So for each artist
whose via-song doesn't resolve, this script retries the NEXT candidate song
on the SAME edge (shortest-title-first, matching U2's own tie-break) until
one resolves or every song on the edge has been tried — and REWIRES
`via_song_id` to the winner, so the served chain shows a playable song
whenever the edge has one, not just whichever song happened to be picked
first.

Resumability + rate hygiene (same idiom as spotify_enrich.py): a song already
carrying a real id or the NO_TRACK_SENTINEL is never re-searched (its result
is reused directly, at zero network cost) — this is what makes trying
siblings on a resumed run cheap even when most of them were already resolved
to "none" in a prior run. A 429 aborts the WHOLE run cleanly (Retry-After
honored); any other transient failure leaves the CURRENT candidate unresolved
so a later run retries at the same point.

CLI:
    python3 src/track_prebake.py --db data/collaboration_network_mb.db
    python3 src/track_prebake.py --db <db> --limit 20000   # top-N by priority
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from database import CollaborationDatabase, NO_TRACK_SENTINEL  # noqa: E402
from spotify_enrich import (  # noqa: E402
    RateLimited,
    _accept_track,
    _build_query,
    get_client_token,
    search_track,
)

DEFAULT_TIMEOUT = 6.0
DEFAULT_RATE = 4.5  # requests/sec ceiling (KTD5: ~4-5)
CHUNK = 200  # commit progress every N artists (bounds loss on interrupt)


def _edge_key(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _resolve_track_id_for_song(song_name: str, artist_names: List[str],
                               candidates: List[dict]) -> str:
    """Same accept-logic as spotify_enrich._resolve_track_id — the first
    candidate that passes the title+artist guard wins, else the sentinel."""
    for track in candidates:
        tid = track.get("id")
        if tid and _accept_track(song_name, artist_names, track):
            return tid
    return NO_TRACK_SENTINEL


def resolve_artist_edge(
    edge_songs: List[Dict],
    token: str,
    *,
    search: Callable[[str, str, float], List[dict]] = search_track,
    timeout: float = DEFAULT_TIMEOUT,
    pace: Callable[[], None] = lambda: None,
) -> Tuple[Optional[Tuple[int, str]], List[Tuple[int, str]]]:
    """
    Try each candidate song on one edge, shortest-title-first (matching U2's
    tie-break), until one resolves to a real track id or every candidate is
    exhausted.

    Returns (winner, sentinel_writes):
      winner = (song_id, track_id) for the first song that resolves — either
               already-stored or newly resolved this call — or None if every
               candidate is a confirmed miss.
      sentinel_writes = [(song_id, NO_TRACK_SENTINEL), ...] for candidates
               searched THIS call that came back with no acceptable match;
               the caller persists these regardless of whether a winner was
               found, so a re-run never re-searches them.

    Raises on a transient network/HTTP failure (RateLimited or
    requests.RequestException/ValueError) from `search` — the caller decides
    whether to abort the whole run (RateLimited) or just leave this artist
    for a later retry (anything else). Any sentinel_writes gathered before
    the raise are lost with it — a minor, acceptable re-check cost on the
    next run, not a correctness issue (already-sentinel songs from a prior
    run are still skipped for free below).
    """
    ordered = sorted(edge_songs, key=lambda s: (len(s["name"]), s["id"]))
    sentinel_writes: List[Tuple[int, str]] = []

    for song in ordered:
        current_id = song.get("spotify_track_id")
        if current_id and current_id != NO_TRACK_SENTINEL:
            return (song["id"], current_id), sentinel_writes
        if current_id == NO_TRACK_SENTINEL:
            continue  # already a confirmed miss from a prior run — free skip

        collaborators = song.get("collaborators") or []
        query = _build_query(song["name"], collaborators)
        candidates = search(query, token, timeout)
        pace()
        track_id = _resolve_track_id_for_song(song["name"], collaborators, candidates)
        if track_id == NO_TRACK_SENTINEL:
            sentinel_writes.append((song["id"], NO_TRACK_SENTINEL))
            continue
        return (song["id"], track_id), sentinel_writes

    return None, sentinel_writes


def prebake_tracks(
    db: CollaborationDatabase,
    token: Optional[str] = None,
    limit: Optional[int] = None,
    rate: float = DEFAULT_RATE,
    timeout: float = DEFAULT_TIMEOUT,
    search: Callable[[str, str, float], List[dict]] = search_track,
    artist_ids: Optional[List[str]] = None,
    log: Callable[[str], None] = print,
) -> Dict[str, int]:
    """
    Resolve and persist Spotify track ids for path-tree via-songs, retrying
    sibling songs on the same edge on a miss. Returns a summary dict:
    {'candidates', 'processed', 'resolved', 'no_player', 'errors', 'aborted'}.

    'resolved' = the artist's edge now has a playable id (possibly on a
    rewired via_song_id); 'no_player' = every song on the edge was searched
    and none had an acceptable match; 'errors' = a transient failure left the
    artist unresolved for a later run; 'aborted' = 1 if a 429 stopped the
    run early.

    `artist_ids`, when given, force-resolves exactly this set (e.g. a
    showcase demo's chain hops, plan 2026-07-09-001, U5) instead of the
    normal predecessor-popularity priority queue.
    """
    candidates = db.get_artists_needing_track_ids(limit=limit, artist_ids=artist_ids)
    edge_songs = db.get_all_edge_songs()
    min_interval = (1.0 / rate) if rate and rate > 0 else 0.0

    processed = resolved = no_player = errors = 0
    aborted = 0
    rewire_batch: List[Tuple[str, int]] = []
    # Holds (song_id, value) writes for songs.spotify_track_id — BOTH the
    # NO_TRACK_SENTINEL misses gathered along the way AND the winning real id
    # itself, so a freshly-resolved track id actually gets persisted (not
    # just remembered for the via_song_id rewire).
    track_id_batch: List[Tuple[int, str]] = []

    def flush():
        if rewire_batch:
            db.set_via_song_id_bulk(rewire_batch)
            rewire_batch.clear()
        if track_id_batch:
            db.set_spotify_track_id_bulk(track_id_batch)
            track_id_batch.clear()

    def pace():
        if min_interval:
            time.sleep(min_interval)

    for cand in candidates:
        key = _edge_key(cand["predecessor_id"], cand["artist_id"])
        songs = edge_songs.get(key, [])
        try:
            winner, new_sentinels = resolve_artist_edge(
                songs, token, search=search, timeout=timeout, pace=pace)
        except RateLimited as rl:
            aborted = 1
            wait = f" (Retry-After: {rl.retry_after}s)" if rl.retry_after else ""
            log(f"  429 rate limit — aborting cleanly{wait}; "
                f"{processed} done, rest left for resume.")
            break
        except (requests.RequestException, ValueError):
            errors += 1
            continue

        track_id_batch.extend(new_sentinels)
        if winner:
            song_id, track_id = winner
            track_id_batch.append((song_id, track_id))
            if song_id != cand["via_song_id"]:
                rewire_batch.append((cand["artist_id"], song_id))
            resolved += 1
        else:
            no_player += 1
        processed += 1

        if len(rewire_batch) + len(track_id_batch) >= CHUNK:
            flush()
            log(f"  ...{processed} processed ({resolved} resolved, {no_player} no-player)")

    flush()
    return {
        "candidates": len(candidates),
        "processed": processed,
        "resolved": resolved,
        "no_player": no_player,
        "errors": errors,
        "aborted": aborted,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve + persist Spotify track ids for path-tree connecting songs.")
    parser.add_argument("--db", required=True, help="Path to the built SQLite DB.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap the number of artists this run, top-N by "
                             "predecessor popularity (measure a pass, or "
                             "bound to e.g. the top 20k).")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE,
                        help="Max Spotify search requests/sec.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--seed-ids", default=None,
                        help="Comma-separated artist ids to force-resolve "
                             "(e.g. a demo's showcase chain hops), ignoring "
                             "the predecessor-popularity priority queue.")
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

    seed_ids = [s.strip() for s in args.seed_ids.split(",") if s.strip()] if args.seed_ids else None

    db = CollaborationDatabase(str(db_path))
    to_do = len(db.get_artists_needing_track_ids(limit=args.limit, artist_ids=seed_ids))
    print(f"Resolving track ids for up to {to_do} artists' via-songs "
          f"(limit={args.limit}, seeded={bool(seed_ids)})...")

    summary = prebake_tracks(db, token=token, limit=args.limit,
                             rate=args.rate, timeout=args.timeout,
                             artist_ids=seed_ids)

    print("Done." if not summary["aborted"] else "Aborted (rate limit).")
    print(f"  candidates:   {summary['candidates']:>8}")
    print(f"  processed:    {summary['processed']:>8}")
    print(f"  resolved:     {summary['resolved']:>8}")
    print(f"  no player:    {summary['no_player']:>8}")
    print(f"  errors:       {summary['errors']:>8}")
    if summary["processed"]:
        playable_rate = summary["resolved"] / summary["processed"] * 100
        print(f"  playable rate among processed: {playable_rate:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
