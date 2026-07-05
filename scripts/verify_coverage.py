"""
U6 — Verify coverage and delight of the MusicBrainz collaboration graph.

Works at any depth. For the depth-3 rebuild (KTD11) this is the guardrail:
run it against the *candidate* DB (before promotion) and judge it against the
Verification Contract — graph size stays sane, Sinatra/Bowie resolve via REAL
chains, and the spurious/novelty-Official edge surface is re-measured, not
assumed unchanged from depth 2.

Reports honestly (no data hand-curation):
- node/edge counts, optionally vs a baseline DB (e.g. the live depth-2 graph),
- degree distribution + path-length summary from Kendrick,
- target lookups WITH their full path + connecting song per hop,
- a cross-genre no-connection rate,
- a NON-EXHAUSTIVE novelty/troll-bridge flag over every path shown.

Records the KNOWN caveat (accepted 2026-07-04): MusicBrainz contains
novelty/troll recordings that are marked Official, so the release-status
filter does not remove them (e.g. "Friday Part 3" by "Hanging Dong"). There is
no clean structural signal for these, so the flag below is a heuristic
watchlist for human review — NOT an exhaustive detector.

CLI:
    python3 scripts/verify_coverage.py                       # live MB DB
    python3 scripts/verify_coverage.py --db data/collaboration_network_mb_d3.db \
        --compare-to data/collaboration_network_mb.db        # depth-3 candidate vs live
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import deque
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from database import CollaborationDatabase, build_adjacency_list  # noqa: E402
from path_finder_sqlite import PathFinder  # noqa: E402

MB_DB = _ROOT / "data" / "collaboration_network_mb.db"
SPOTIFY_DB = _ROOT / "data" / "collaboration_network.db"
KENDRICK_MBID = "381086ea-f511-4aba-bdf9-71c753dc5077"

# Soft explosion signal: warn if the candidate graph grows more than this
# multiple over the baseline. Informational — the "sane bound" is a judgment
# call the plan says to RECORD, not a hard gate.
EXPLOSION_FACTOR = 15.0

# Non-exhaustive watchlist for the novelty/troll-bridge flag. Substrings matched
# case-insensitively against path artist names and connecting song titles. This
# exists for human review, NOT as a detector — by design (KTD10) these have no
# clean structural signal, so new ones will not be caught here.
NOVELTY_ARTIST_HINTS = ["hanging dong"]
NOVELTY_SONG_HINTS = ["friday part 3"]

# Cross-genre delight spot-check (matched by name/alias in the graph).
SPOT_CHECK = [
    "SZA", "Drake", "Rihanna", "The Weeknd", "Beyoncé", "Taylor Swift",
    "Ariana Grande", "Ed Sheeran", "Eminem", "Snoop Dogg", "Dr. Dre",
    "Paul McCartney", "The Beatles", "Frank Sinatra", "Miles Davis",
    "Adele", "Coldplay", "U2", "Madonna", "Michael Jackson",
    "Elton John", "David Bowie", "Radiohead", "Kanye West", "Ye",
]

# Targets whose full path we print + inspect for legitimacy.
TARGETS = ["Paul McCartney", "The Beatles", "Frank Sinatra", "David Bowie"]


def degree_distribution(db, seed):
    """Return (histogram {depth: count}, dist {node: depth}) via BFS from seed."""
    adj = build_adjacency_list(db)
    dist = {seed: 0}
    q = deque([seed])
    while q:
        n = q.popleft()
        for nb in adj.get(n, []):
            if nb not in dist:
                dist[nb] = dist[n] + 1
                q.append(nb)
    hist = {}
    for d in dist.values():
        hist[d] = hist.get(d, 0) + 1
    return hist, dist


def path_with_songs(conn):
    """'A -[song]-> B -[song]-> Kendrick' from a find_connection result."""
    names = [p["name"] for p in conn["path"]]
    hops = conn["connections"]
    parts = [names[0]]
    for i, hop in enumerate(hops):
        song = hop["songs"][0] if hop.get("songs") else "?"
        parts.append(f"-[{song}]-> {names[i + 1]}")
    return " ".join(parts)


def novelty_flags(conn):
    """Return a list of watchlist hits (artist or song) on this path — for human
    review only. Empty list = nothing on the (non-exhaustive) watchlist."""
    hits = []
    for p in conn["path"]:
        nm = (p["name"] or "").lower()
        for hint in NOVELTY_ARTIST_HINTS:
            if hint in nm:
                hits.append(f"artist~'{p['name']}'")
    for hop in conn["connections"]:
        for song in hop.get("songs", []):
            s = (song or "").lower()
            for hint in NOVELTY_SONG_HINTS:
                if hint in s:
                    hits.append(f"song~'{song}'")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify coverage/delight of the MB graph")
    ap.add_argument("--db", default=str(MB_DB),
                    help="graph DB to verify (default: live MB DB)")
    ap.add_argument("--compare-to", default=None,
                    help="baseline DB to compare size against (e.g. the live depth-2 DB)")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 2
    db = CollaborationDatabase(str(db_path))
    pf = PathFinder(db)
    stats = db.get_stats()

    print("=" * 64)
    print(f"COVERAGE REPORT — {db_path.name}")
    print("=" * 64)
    print(f"\nGraph: {stats['total_artists']:,} artists, "
          f"{stats['total_collaborations']:,} edges, {stats['total_songs']:,} songs")

    # --- size guardrail: compare against a baseline if given ------------------
    if args.compare_to:
        base_path = Path(args.compare_to)
        if base_path.exists():
            base = CollaborationDatabase(str(base_path)).get_stats()
            print(f"Baseline ({base_path.name}): {base['total_artists']:,} artists, "
                  f"{base['total_collaborations']:,} edges")
            if base["total_artists"]:
                factor = stats["total_artists"] / base["total_artists"]
                print(f"  growth: {factor:.1f}x artists vs baseline")
                if factor > EXPLOSION_FACTOR:
                    print(f"  ⚠️  SIZE WARNING: >{EXPLOSION_FACTOR:.0f}x growth — "
                          f"inspect whether reach is real or an explosion.")
        else:
            print(f"(baseline {base_path} not found; skipping size comparison)")

    # --- path-length summary (delight signal) --------------------------------
    print("\n-- Reach from Kendrick --")
    hist, dist = degree_distribution(db, KENDRICK_MBID)
    depths = [d for d in dist.values() if d > 0]  # exclude Kendrick himself
    max_depth = max(hist) if hist else 0
    reachable = len(dist) - 1
    for d in sorted(hist):
        pct = 100.0 * hist[d] / len(dist)
        print(f"  degree {d}: {hist[d]:,} artists ({pct:.1f}%)")
    if depths:
        print(f"  reachable: {reachable:,} | median hops: {statistics.median(depths):.1f} "
              f"| mean: {statistics.mean(depths):.2f} | max: {max_depth}")
        frac_at_max = 100.0 * hist.get(max_depth, 0) / len(dist)
        # Delight signal: if the vast majority sit at the outer ring, "N degrees"
        # stops being a surprise. Informational, for the human to weigh.
        if frac_at_max > 70.0:
            print(f"  ⚠️  DELIGHT WATCH: {frac_at_max:.0f}% of artists sit at the outer "
                  f"ring (degree {max_depth}) — a short path may feel less special.")

    # --- target lookups WITH full path + legitimacy inspection ---------------
    print("\n-- Target lookups (inspect hops for REAL chains) --")
    for name in TARGETS:
        a = db.get_artist_by_name(name)
        if not a:
            print(f"  {name}: NOT in graph -> no connection")
            continue
        conn = pf.find_connection(a["id"], KENDRICK_MBID)
        if not conn:
            print(f"  {name}: present but no path -> no connection")
            continue
        flags = novelty_flags(conn)
        tag = f"  ⚠️  novelty-watchlist hit: {flags}" if flags else ""
        print(f"  {name}: degree {conn['degrees']}")
        print(f"      {path_with_songs(conn)}{tag}")

    # --- cross-genre no-connection rate + novelty sweep ----------------------
    print("\n-- Cross-genre spot-check (no-connection rate) --")
    found = missing = 0
    missing_names = []
    novelty_hits = []
    for name in SPOT_CHECK:
        a = db.get_artist_by_name(name)
        conn = pf.find_connection(a["id"], KENDRICK_MBID) if a else None
        if conn:
            found += 1
            if novelty_flags(conn):
                novelty_hits.append(name)
        else:
            missing += 1
            missing_names.append(name)
    total = found + missing
    print(f"  connected: {found}/{total} | no-connection: {missing}/{total}")
    if missing_names:
        print(f"  not reachable: {missing_names}")
    print(f"  novelty-watchlist bridges among reachable targets: "
          f"{novelty_hits if novelty_hits else 'none (watchlist is NON-exhaustive)'}")

    print("\n-- KNOWN CAVEAT (accepted 2026-07-04) --")
    print("  MusicBrainz has novelty/troll recordings marked Official; the status")
    print("  filter cannot remove them and there's no clean structural signal.")
    print("  The flag above is a heuristic watchlist for review, NOT a detector —")
    print("  reported honestly, not hand-blocklisted (delight-over-completeness).")
    print("  At depth 3, eyeball the target paths above: hops must carry REAL")
    print("  co-credited songs, not mix/novelty artifacts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
