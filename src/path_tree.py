"""
U2 — Single-source shortest-path tree precompute (plan 2026-07-09-001, KTD1).

The public app has one fixed destination: Kendrick Lamar. Computing a live BFS
per request (the current `PathFinder`) means every visitor forces the whole
369k-edge graph into RAM. Since the destination never changes, the path from
every artist TO Kendrick can be computed ONCE, offline: for each artist, its
distance from Kendrick, its predecessor on the shortest path, and a
representative connecting song. Serving a connection then degrades to walking
`predecessor_id` a handful of times — no graph, no runtime BFS.

This mirrors the verified prior art (sixdegreesofkanyewest.com's
`kanye_degree` table: gen/ancestor/track per artist), adapted to a
single-source-from-Kendrick BFS instead of a single-source-from-Kanye one
(the direction is the same; Kendrick is the root here).

Design:
- Not resumable in the network-enrichment sense (src/popularity_enrich.py,
  src/spotify_enrich.py) — there's no external API to rate-limit against.
  The whole graph fits in memory and a full BFS is fast, so every run fully
  recomputes and overwrites (`set_path_tree_bulk`), which is also what keeps
  the precompute correct after the graph itself changes.
- Predecessor tie-break: when several already-visited (frontier) artists
  reach the same unvisited node in one BFS round, the more popular one wins
  (`get_all_popularity`), then the lower artist id for full determinism —
  same "stable ordering" idiom as `disambiguate_labels`.
- Via-song tie-break: among the songs on the winning edge, prefer the
  shortest title (a weak proxy for "more likely to resolve on Spotify" — a
  short, exact title reduces false-negative search misses), then the lower
  song id. U4 (track-ID pre-bake) may later overwrite `via_song_id` with a
  sibling song from the same edge if this pick fails to resolve.

CLI:
    python3 src/path_tree.py --db data/collaboration_network_mb.db
    python3 src/path_tree.py --db <db> --kendrick-id <mbid>   # override lookup
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from database import CollaborationDatabase  # noqa: E402
from path_finder_sqlite import PathFinder  # noqa: E402

DEFAULT_KENDRICK_NAME = "Kendrick Lamar"

# Path row: (kendrick_distance, predecessor_id, via_song_id) — all None for
# Kendrick himself and for artists the BFS never reaches.
PathRow = Tuple[Optional[int], Optional[str], Optional[int]]


class KendrickNotFoundError(Exception):
    """Raised when the root artist can't be resolved — nothing to build a
    path tree toward."""


def resolve_kendrick_id(db: CollaborationDatabase, override: Optional[str] = None) -> str:
    """Resolve the root artist id: explicit override, else RABBITHOLE_KENDRICK_ID
    env var, else a by-name lookup — same precedence as api/main.py's
    `_get_db` so the precompute and the live app always agree on the root."""
    if override:
        return override
    env = os.environ.get("RABBITHOLE_KENDRICK_ID")
    if env:
        return env
    artist = db.get_artist_by_name(DEFAULT_KENDRICK_NAME)
    if not artist:
        raise KendrickNotFoundError(
            f"No artist named {DEFAULT_KENDRICK_NAME!r} in the DB, and neither "
            "--kendrick-id nor RABBITHOLE_KENDRICK_ID was set. Nothing to root "
            "the path tree on."
        )
    return artist["id"]


def _pick_predecessor(candidates: List[str], popularity: Dict[str, int]) -> str:
    """Highest popularity wins; lowest id breaks a tie, for full determinism
    across reruns."""
    return min(candidates, key=lambda p: (-popularity.get(p, 0), p))


def _pick_via_song(
    predecessor_id: str, artist_id: str, edge_songs: Dict[Tuple[str, str], List[Dict]]
) -> Optional[int]:
    """Shortest title wins (weak proxy for Spotify-search resolvability);
    lowest song id breaks a tie. None only if the edge has no songs at all,
    which should not happen for a real collaboration edge."""
    key = (predecessor_id, artist_id) if predecessor_id < artist_id else (artist_id, predecessor_id)
    candidates = edge_songs.get(key)
    if not candidates:
        return None
    best = min(candidates, key=lambda s: (len(s["name"]), s["id"]))
    return best["id"]


def compute_path_tree(
    db: CollaborationDatabase, kendrick_id: str
) -> Dict[str, PathRow]:
    """
    Single-source BFS from `kendrick_id` over the full collaboration graph.
    Returns {artist_id: (distance, predecessor_id, via_song_id)} for EVERY
    artist in the DB — reachable artists get real values, unreachable ones
    get (None, None, None), which the caller persists as-is (the frontend's
    existing "not in network" path already treats NULL distance honestly).
    """
    from database import build_adjacency_list

    adjacency = build_adjacency_list(db)
    popularity = db.get_all_popularity()
    edge_songs = db.get_all_edge_songs()
    all_artist_ids = db.get_all_artist_ids()

    distance: Dict[str, int] = {kendrick_id: 0}
    predecessor: Dict[str, str] = {}
    frontier = [kendrick_id]
    d = 0

    while frontier:
        next_candidates: Dict[str, List[str]] = {}
        for node in frontier:
            for neighbor in adjacency.get(node, []):
                if neighbor not in distance:
                    next_candidates.setdefault(neighbor, []).append(node)

        next_frontier = []
        for node, preds in next_candidates.items():
            distance[node] = d + 1
            predecessor[node] = _pick_predecessor(preds, popularity)
            next_frontier.append(node)

        frontier = next_frontier
        d += 1

    result: Dict[str, PathRow] = {}
    for artist_id in all_artist_ids:
        if artist_id == kendrick_id:
            result[artist_id] = (0, None, None)
            continue
        dist = distance.get(artist_id)
        if dist is None:
            result[artist_id] = (None, None, None)
            continue
        pred = predecessor[artist_id]
        via_song = _pick_via_song(pred, artist_id, edge_songs)
        result[artist_id] = (dist, pred, via_song)

    return result


def persist_path_tree(db: CollaborationDatabase, tree: Dict[str, PathRow]) -> None:
    rows = [(artist_id, dist, pred, song) for artist_id, (dist, pred, song) in tree.items()]
    db.set_path_tree_bulk(rows)


def summarize(tree: Dict[str, PathRow]) -> Dict[str, int]:
    """Distance histogram + reachability counts for the run's printed summary."""
    histogram: Dict[int, int] = {}
    unreachable = 0
    for _artist_id, (dist, _pred, _song) in tree.items():
        if dist is None:
            unreachable += 1
        else:
            histogram[dist] = histogram.get(dist, 0) + 1
    return {"histogram": histogram, "unreachable": unreachable, "total": len(tree)}


def validate(db: CollaborationDatabase, kendrick_id: str, sample_size: int = 50) -> List[str]:
    """
    Full-table invariants (every row, not just a sample — the precomputed
    rows ARE the served product forever, so systematic corruption anywhere
    in the table matters) plus a live-BFS agreement sample. Returns a list of
    problem descriptions; empty means every check passed.
    """
    problems: List[str] = []
    rows = db.get_all_path_tree_rows()
    by_id = {r["id"]: r for r in rows}

    # Invariant: exactly one row (Kendrick) has distance 0.
    zero_distance = [r["id"] for r in rows if r["kendrick_distance"] == 0]
    if zero_distance != [kendrick_id]:
        problems.append(
            f"expected exactly one distance-0 row ({kendrick_id!r}), found {zero_distance!r}"
        )

    edge_songs = db.get_all_edge_songs()
    for r in rows:
        aid, dist, pred, song = r["id"], r["kendrick_distance"], r["predecessor_id"], r["via_song_id"]
        if aid == kendrick_id:
            continue
        if dist is None:
            if pred is not None or song is not None:
                problems.append(f"{aid}: unreachable (distance NULL) but predecessor/song set")
            continue
        # Invariant: predecessor exists and sits at distance - 1.
        if pred is None:
            problems.append(f"{aid}: distance {dist} but no predecessor")
            continue
        pred_row = by_id.get(pred)
        if pred_row is None or pred_row["kendrick_distance"] != dist - 1:
            problems.append(
                f"{aid}: predecessor {pred!r} is not at distance {dist - 1} "
                f"(got {pred_row['kendrick_distance'] if pred_row else 'missing'})"
            )
        # Invariant: (predecessor, artist) is a real collaboration edge.
        key = (pred, aid) if pred < aid else (aid, pred)
        songs_on_edge = edge_songs.get(key)
        if not songs_on_edge:
            problems.append(f"{aid}: no collaboration edge to predecessor {pred!r}")
            continue
        # Invariant: via_song belongs to that edge.
        if song is not None and song not in {s["id"] for s in songs_on_edge}:
            problems.append(f"{aid}: via_song {song} does not belong to the {pred!r}<->{aid} edge")

    # Sample cross-check against the live BFS oracle (deterministic stride,
    # not random, so runs are reproducible).
    reachable_ids = sorted(r["id"] for r in rows if r["kendrick_distance"] is not None)
    if reachable_ids:
        stride = max(1, len(reachable_ids) // sample_size)
        sample = reachable_ids[::stride][:sample_size]
        finder = PathFinder(db)
        for artist_id in sample:
            live_path = finder.find_path(artist_id, kendrick_id)
            live_distance = (len(live_path) - 1) if live_path else None
            precomputed_distance = by_id[artist_id]["kendrick_distance"]
            if live_distance != precomputed_distance:
                problems.append(
                    f"{artist_id}: precomputed distance {precomputed_distance} "
                    f"disagrees with live BFS distance {live_distance}"
                )

    return problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Precompute the single-source shortest-path tree from Kendrick Lamar."
    )
    parser.add_argument("--db", required=True, help="Path to the built SQLite DB.")
    parser.add_argument("--kendrick-id", default=None, help="Override the root artist id.")
    parser.add_argument("--skip-validate", action="store_true",
                        help="Skip the post-build validation pass.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: DB not found at {db_path}", file=sys.stderr)
        return 1

    db = CollaborationDatabase(str(db_path))
    try:
        kendrick_id = resolve_kendrick_id(db, args.kendrick_id)
    except KendrickNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Building path tree rooted at {kendrick_id!r}...")
    tree = compute_path_tree(db, kendrick_id)
    persist_path_tree(db, tree)

    stats = summarize(tree)
    reached = stats["total"] - stats["unreachable"]
    print(f"Done. {reached}/{stats['total']} artists reachable "
          f"({stats['unreachable']} unreachable).")
    for dist in sorted(stats["histogram"]):
        print(f"  distance {dist}: {stats['histogram'][dist]}")

    if not args.skip_validate:
        print("Validating...")
        problems = validate(db, kendrick_id)
        if problems:
            print(f"VALIDATION FAILED ({len(problems)} problem(s)):", file=sys.stderr)
            for p in problems[:20]:
                print(f"  - {p}", file=sys.stderr)
            if len(problems) > 20:
                print(f"  ...and {len(problems) - 20} more", file=sys.stderr)
            return 1
        print("Validation passed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
