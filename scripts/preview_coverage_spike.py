"""
Plan 007 U1 — Popularity-weighted preview-coverage spike.

Measures Spotify-id resolvability on songs the app ACTUALLY DISPLAYS (deduped
connecting songs on real shortest paths from a basket of famous search targets
to Kendrick), NOT a raw table scan (which surfaces compilation hubs, not pop).

Primary source measured: ListenBrainz `spotify-id-from-metadata` (artist+title;
batchable; matched against Spotify's real catalog; no recording MBID needed —
which our DB lacks). This is the source that decides Path A vs Path B.

The MB-URL-link source is a known ~4.6% floor from the session's dump scan (it
needs recording MBIDs to measure per-song, which our built DB doesn't store).

Usage: python3 scripts/preview_coverage_spike.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
from database import CollaborationDatabase  # noqa: E402
from path_finder_sqlite import PathFinder  # noqa: E402

DB_PATH = _ROOT / "data" / "collaboration_network_mb.db"
LB_META = "https://labs.api.listenbrainz.org/spotify-id-from-metadata/json"
UA = "RabbitHole/0.1 (jorsanto@umich.edu) preview-coverage-spike"

# A basket of famous, cross-genre, cross-era search targets = the demo's real
# traffic (curious fans typing popular names). Deliberately spans rap, pop, R&B,
# rock, and older acts so coverage isn't measured only on new hip-hop.
TARGETS = [
    "Drake", "Rihanna", "Taylor Swift", "The Weeknd", "Beyoncé", "SZA",
    "Travis Scott", "Frank Ocean", "Kanye West", "Bad Bunny", "Billie Eilish",
    "Dua Lipa", "Baby Keem", "Larry June", "Dom Kennedy", "Snoop Dogg",
    "Eminem", "J. Cole", "Doja Cat", "Mariah Carey", "Frank Sinatra",
    "David Bowie", "Metro Boomin", "Anderson .Paak", "Bruno Mars",
]

DISPLAY_SONGS_PER_EDGE = 3  # mirror the UI (connection-view slices to 3)


def collect_displayed_songs(db, finder, kendrick_id):
    """Return list of dicts: {'title', 'artists'(lineup), 'via'(target)} for the
    songs actually shown on the shortest paths of our basket."""
    songs = []
    seen = set()
    resolved_targets = 0
    for name in TARGETS:
        cands = db.resolve_artist(name, limit=1)
        if not cands:
            print(f"  [skip] no artist match: {name}")
            continue
        conn = finder.find_connection(cands[0]["id"], kendrick_id)
        if not conn or not conn.get("connections"):
            print(f"  [skip] no path: {name}")
            continue
        resolved_targets += 1
        for edge in conn["connections"]:
            for sd in edge["song_details"][:DISPLAY_SONGS_PER_EDGE]:
                title = sd["name"]
                lineup = sd.get("collaborators") or []
                # fall back to the edge endpoints if lineup wasn't captured
                if not lineup:
                    lineup = [edge["from"]["name"], edge["to"]["name"]]
                key = (title.lower(), tuple(sorted(a.lower() for a in lineup)))
                if key in seen:
                    continue
                seen.add(key)
                songs.append({"title": title, "artists": lineup, "via": name})
    return songs, resolved_targets


def lb_metadata_hits(songs):
    """For each song, build (artist, title) candidate rows from its credited
    lineup and query ListenBrainz. A song counts as resolved if ANY candidate
    returns a non-empty spotify_track_ids. Returns (resolved_count, rows_sent)."""
    rows = []
    row_owner = []  # index into songs for each row
    for i, s in enumerate(songs):
        cands = list(dict.fromkeys(a for a in s["artists"] if a))[:4]  # dedup, cap 4
        for artist in cands:
            rows.append({"artist_name": artist, "release_name": "", "track_name": s["title"]})
            row_owner.append(i)

    hit = [False] * len(songs)
    # Batch in chunks well under the observed 5000-row ceiling.
    CHUNK = 800
    for start in range(0, len(rows), CHUNK):
        batch = rows[start:start + CHUNK]
        resp = requests.post(LB_META, json=batch,
                             headers={"Content-Type": "application/json", "User-Agent": UA},
                             timeout=60)
        resp.raise_for_status()
        for j, item in enumerate(resp.json()):
            if item.get("spotify_track_ids"):
                hit[row_owner[start + j]] = True
        time.sleep(1.0)  # polite pacing (labs exposes no rate headers)
    return sum(hit), len(rows)


def main():
    if not DB_PATH.exists():
        print(f"error: DB not found at {DB_PATH}", file=sys.stderr)
        return 1
    db = CollaborationDatabase(str(DB_PATH))
    finder = PathFinder(db)
    kart = db.get_artist_by_name("Kendrick Lamar")
    if not kart:
        print("error: Kendrick not found", file=sys.stderr)
        return 1
    kendrick_id = kart["id"]

    print(f"Collecting displayed songs for {len(TARGETS)} famous targets...")
    songs, n_targets = collect_displayed_songs(db, finder, kendrick_id)
    print(f"\n{n_targets}/{len(TARGETS)} targets had a path; "
          f"{len(songs)} unique displayed songs collected.\n")
    if not songs:
        print("No displayed songs — cannot measure.")
        return 1

    print("Querying ListenBrainz spotify-id-from-metadata (artist+title)...")
    lb_hits, rows_sent = lb_metadata_hits(songs)

    print("\n" + "=" * 60)
    print("PREVIEW-COVERAGE SPIKE — displayed songs (popularity-weighted)")
    print("=" * 60)
    print(f"targets with a path:        {n_targets}/{len(TARGETS)}")
    print(f"unique displayed songs:     {len(songs)}")
    print(f"LB metadata query rows:     {rows_sent}")
    print("-" * 60)
    print(f"ListenBrainz (metadata):    {lb_hits}/{len(songs)} = "
          f"{100*lb_hits/len(songs):.1f}%   <- decisive offline source")
    print(f"MusicBrainz URL links:      ~4.6% (session dump scan; needs MBIDs to measure per-song)")
    print("-" * 60)
    pct = 100 * lb_hits / len(songs)
    if pct >= 60:
        rec = "PATH A — build offline pipeline (ListenBrainz primary), lazy tail"
    elif pct < 40:
        rec = "PATH B — lazy-resolve-on-Play + persist (offline pre-bake not worth it)"
    else:
        rec = f"JUDGMENT BAND ({pct:.0f}%) — weigh build cost; lean lazy-only"
    print(f"Decision rule (KTD2 60/40): {rec}")
    print("=" * 60)
    # sample of misses for qualitative sanity
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
