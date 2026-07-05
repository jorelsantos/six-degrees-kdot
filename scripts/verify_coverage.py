"""
U6 — Verify coverage and delight of the MusicBrainz depth-2 graph.

Reports honestly (no data hand-curation):
- node/edge counts vs the retained Spotify baseline,
- degree distribution from Kendrick,
- target lookups (McCartney, The Beatles, Frank Sinatra),
- a cross-genre "no connection at depth 2" spot-check rate.

Records the KNOWN caveat (accepted 2026-07-04): MusicBrainz contains
novelty/troll recordings that are marked Official, so the release-status
filter does not remove them. One such track ("Friday Part 3" by the troll
artist "Hanging Dong", crediting McCartney/Kanye/Kendrick/Cher) makes The
Beatles reachable via Paul McCartney. We accept and report this rather than
hand-blocklisting artists.
"""

from __future__ import annotations

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

# Cross-genre delight spot-check (matched by name in the graph).
SPOT_CHECK = [
    "SZA", "Drake", "Rihanna", "The Weeknd", "Beyoncé", "Taylor Swift",
    "Ariana Grande", "Ed Sheeran", "Eminem", "Snoop Dogg", "Dr. Dre",
    "Paul McCartney", "The Beatles", "Frank Sinatra", "Miles Davis",
    "Adele", "Coldplay", "U2", "Madonna", "Michael Jackson",
    "Elton John", "David Bowie", "Radiohead", "Kanye West", "Ye",
]


def degree_distribution(db, seed):
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


def main() -> int:
    if not MB_DB.exists():
        print(f"MB DB not found: {MB_DB}")
        return 2
    db = CollaborationDatabase(str(MB_DB))
    pf = PathFinder(db)
    stats = db.get_stats()

    print("=" * 64)
    print("U6 COVERAGE REPORT — MusicBrainz depth-2 graph")
    print("=" * 64)
    print(f"\nMusicBrainz graph: {stats['total_artists']:,} artists, "
          f"{stats['total_collaborations']:,} edges, {stats['total_songs']:,} songs")
    if SPOTIFY_DB.exists():
        sp = CollaborationDatabase(str(SPOTIFY_DB)).get_stats()
        print(f"Spotify baseline : {sp['total_artists']:,} artists, "
              f"{sp['total_collaborations']:,} edges "
              f"(broad but ~12% crawled, incomplete)")

    print("\n-- Degree distribution from Kendrick (MB graph) --")
    hist, dist = degree_distribution(db, KENDRICK_MBID)
    for d in sorted(hist):
        print(f"  degree {d}: {hist[d]:,} artists")

    print("\n-- Target lookups --")
    for name in ["Paul McCartney", "The Beatles", "Frank Sinatra"]:
        a = db.get_artist_by_name(name)
        if not a:
            print(f"  {name}: NOT in depth-2 graph -> no connection")
            continue
        conn = pf.find_connection(a["id"], KENDRICK_MBID)
        if not conn:
            print(f"  {name}: present but no path -> no connection")
        else:
            path = " -> ".join(p["name"] for p in conn["path"])
            first_song = conn["connections"][0]["songs"][0] if conn["connections"][0]["songs"] else "?"
            print(f"  {name}: degree {conn['degrees']} | {path}")
            print(f"      (first hop via {first_song!r})")

    print("\n-- Cross-genre spot-check (no-connection rate at depth 2) --")
    found = missing = 0
    missing_names = []
    for name in SPOT_CHECK:
        a = db.get_artist_by_name(name)
        conn = pf.find_connection(a["id"], KENDRICK_MBID) if a else None
        if conn:
            found += 1
        else:
            missing += 1
            missing_names.append(name)
    total = found + missing
    print(f"  connected: {found}/{total} | no-connection: {missing}/{total}")
    if missing_names:
        print(f"  not reachable at depth 2: {missing_names}")

    print("\n-- KNOWN CAVEAT (accepted 2026-07-04) --")
    print("  MusicBrainz has novelty/troll recordings marked Official; the")
    print("  status filter cannot remove them. 'Friday Part 3' (troll artist")
    print("  'Hanging Dong') makes The Beatles reachable via Paul McCartney.")
    print("  Reported honestly, not hand-blocklisted (delight-over-completeness).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
