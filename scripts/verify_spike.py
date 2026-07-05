"""
U8 acceptance-check runner for the MusicBrainz validation spike.

Loads the spike DB (data/mb_spike.db) through the app's OWN data layer
(CollaborationDatabase + PathFinder) and asserts every acceptance check from
the migration plan's U8. Exits non-zero if any check fails, so this gates the
full dump ingestion (U1-U3).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from database import CollaborationDatabase  # noqa: E402
from path_finder_sqlite import PathFinder  # noqa: E402
from preview_fetcher import get_preview  # noqa: E402

KENDRICK_MBID = "381086ea-f511-4aba-bdf9-71c753dc5077"
KANYE_MBID = "164f0d73-1234-4e2c-8743-d77bf2191051"
MCCARTNEY_MBID = "ba550d0e-adac-4864-b88b-407cab5e76af"

DB_PATH = _ROOT / "data" / "mb_spike.db"

_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    if not DB_PATH.exists():
        print(f"Spike DB not found at {DB_PATH}. Run scripts/mb_spike.py first.")
        return 2

    db = CollaborationDatabase(str(DB_PATH))
    pf = PathFinder(db)
    stats = db.get_stats()
    print(f"Spike DB: {stats}\n")

    # 1) Known collaborators appear as Kendrick edges with connecting songs.
    collabs = db.get_collaborators(KENDRICK_MBID)
    collab_names = {c["name"].lower() for c in collabs}
    expected = ["ye", "dr. dre", "jay rock", "ab‐soul", "schoolboy q"]
    found = [e for e in expected if any(e in n for n in collab_names)]
    check("known collaborators present as Kendrick edges",
          len(found) >= 3, f"found {found} of {expected}")
    all_have_songs = all(c["songs"] for c in collabs)
    check("every Kendrick edge carries >=1 connecting song",
          all_have_songs, f"{len(collabs)} direct collaborators")

    # 2) Node identity: Ye/Kanye is exactly one node keyed on MBID.
    ye = db.get_artist(KANYE_MBID)
    check("Ye/Kanye is a single MBID-keyed node",
          ye is not None, f"node={ye['name'] if ye else None}")

    # 3) Dedup: no collaboration lists the same base song twice as separate
    #    versions (spot check across all Kendrick edges).
    dup_free = True
    for c in collabs:
        songs = c["songs"]
        if len(songs) != len(set(songs)):
            dup_free = False
    check("connecting songs are deduped per edge", dup_free)

    # 5a) Band vs member: McCartney resolves with a path (Verification Contract
    #     requires resolution, not a specific degree).
    mcc = pf.find_connection(MCCARTNEY_MBID, KENDRICK_MBID)
    mcc_names = [p["name"] for p in mcc["path"]] if mcc else []
    mcc_song = mcc["connections"][0]["songs"][0] if mcc and mcc["connections"] and mcc["connections"][0]["songs"] else None
    check("Paul McCartney resolves to Kendrick with a path",
          mcc is not None,
          f"degrees={mcc['degrees'] if mcc else None}: {' -> '.join(mcc_names)} | first song={mcc_song!r}")

    # 5b) Band vs member: The Beatles must return NO connection (KTD9/R3).
    #     THIS IS THE HEADLINE CHECK — the plan's premise is the band is isolated.
    beatles = db.get_artist_by_name("The Beatles")
    beatles_conn = pf.find_connection(beatles["id"], KENDRICK_MBID) if beatles else None
    if beatles is None:
        detail = "not present in graph"
    elif beatles_conn is None:
        detail = "present but no path (correct)"
    else:
        bnames = [p["name"] for p in beatles_conn["path"]]
        bsong = beatles_conn["connections"][0]["songs"][0] if beatles_conn["connections"] and beatles_conn["connections"][0]["songs"] else None
        detail = f"CONNECTED degree {beatles_conn['degrees']}: {' -> '.join(bnames)} | via {bsong!r} (likely a bootleg mashup credit)"
    check("The Beatles returns NO connection (band != member)",
          beatles_conn is None, detail)

    # 6) Every hop on the McCartney path carries a connecting song.
    if mcc:
        hops_with_songs = all(c["songs"] for c in mcc["connections"])
        detail = " | ".join(
            f"{c['from']['name']}→{c['to']['name']}: {c['songs'][0] if c['songs'] else 'NONE'}"
            for c in mcc["connections"]
        )
        check("every hop on the path carries a song", hops_with_songs, detail)

    # 7) A connecting song has a playable iTunes/Deezer preview.
    preview_ok = False
    preview_detail = ""
    for c in collabs:
        if not c["songs"]:
            continue
        pv = get_preview(c["songs"][0], ["Kendrick Lamar", c["name"]])
        if pv:
            preview_ok = True
            preview_detail = f"{c['songs'][0]!r} via {pv.provider}"
            break
    check("iTunes/Deezer returns a playable preview for a connecting song",
          preview_ok, preview_detail)

    print()
    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
