"""
Tests for the MusicBrainz dump ingest (U2/U3).

Pure-logic tests plus a synthetic mini-dump run end-to-end: it exercises the
Official-release filter (KTD10), version dedup (KTD8), the depth bound (KTD5),
MBID-keyed nodes (KTD7), and the band-vs-member rule (KTD9) — all without the
39M-row real dump.
"""

import sys
from pathlib import Path

import musicbrainz_ingest as mi
from database import CollaborationDatabase
from path_finder_sqlite import PathFinder


# --- pure logic -------------------------------------------------------------

def test_base_title_and_variants():
    assert mi.base_title("All The Stars") == "all the stars"
    assert mi.base_title("All The Stars (Remix)") == "all the stars"
    assert mi.base_title("All The Stars - Live") == "all the stars"
    assert mi.is_variant_title("HUMBLE. (Remix)")
    assert not mi.is_variant_title("HUMBLE.")


def test_dedup_songs_collapses_versions_prefers_clean():
    songs = mi.dedup_songs(["All The Stars (Remix)", "All The Stars", "All The Stars - Live"])
    assert songs == ["All The Stars"]


def test_dedup_songs_keeps_distinct_and_caps():
    songs = mi.dedup_songs([f"Song {i}" for i in range(10)], cap=3)
    assert len(songs) == 3


# --- synthetic mini-dump ----------------------------------------------------

def _write_tsv(path, rows):
    path.write_text("\n".join("\t".join(str(c) for c in r) for r in rows) + "\n", encoding="utf-8")


def _build_mini_dump(d: Path):
    """Create a tiny mbdump/ with the columns the ingest reads."""
    d.mkdir(parents=True, exist_ok=True)

    # artist: id, gid, name
    _write_tsv(d / "artist", [
        [1, "mbid-K", "Kendrick Lamar"],
        [2, "mbid-S", "SZA"],
        [3, "mbid-Y", "Ye"],
        [4, "mbid-P", "Paul McCartney"],
        [5, "mbid-B", "The Beatles"],
        [6, "mbid-solo", "Solo Guy"],
        [7, "mbid-far", "Far Artist"],
        [8, "mbid-int", "Interviewer"],
        [10, "mbid-mix", "Mix Only Artist"],
    ])

    # artist_credit_name: artist_credit, position, artist, name, join_phrase
    _write_tsv(d / "artist_credit_name", [
        [100, 0, 1, "Kendrick Lamar", " & "], [100, 1, 2, "SZA", ""],       # K+S
        [101, 0, 1, "Kendrick Lamar", " feat. "], [101, 1, 3, "Ye", ""],    # K+Ye
        [102, 0, 3, "Ye", " feat. "], [102, 1, 4, "Paul McCartney", ""],    # Ye+McCartney
        [103, 0, 3, "Ye", " & "], [103, 1, 5, "The Beatles", ""],           # Ye+Beatles (BOOTLEG rec)
        [104, 0, 6, "Solo Guy", ""],                                        # solo -> no edge
        [105, 0, 4, "Paul McCartney", " & "], [105, 1, 7, "Far Artist", ""],# McCartney+Far (depth 3)
        [106, 0, 1, "Kendrick Lamar", " & "], [106, 1, 2, "SZA", ""],       # K+S again (dedup)
        [107, 0, 3, "Ye", " & "], [107, 1, 8, "Interviewer", ""],           # Ye+Interviewer (Interview RG)
        [109, 0, 1, "Kendrick Lamar", " & "], [109, 1, 999, "Ghost", ""],   # dangling artist 999
        [110, 0, 1, "Kendrick Lamar", " / "], [110, 1, 10, "Mix Only Artist", ""],  # DJ-mix blend
        [111, 0, 1, "Kendrick Lamar", ", "], [111, 1, 2, "SZA", " & "], [111, 2, 3, "Ye", ""],  # 3-artist posse cut
    ])

    # recording: id, gid, name, artist_credit
    _write_tsv(d / "recording", [
        [1000, "r-k", "All the Stars", 100],
        [1001, "r-k", "No More Parties in LA", 101],
        [1002, "r-k", "All Day", 102],
        [1003, "r-k", "Southside My Dear", 103],   # bootleg-only
        [1004, "r-k", "Solo Song", 104],
        [1005, "r-k", "Far Song", 105],
        [1006, "r-k", "All the Stars (Remix)", 106],  # dedups with 1000
        [1007, "r-k", "The Interview", 107],        # interview release-group
        [1009, "r-k", "Ghost Song", 109],
        [1010, "r-k", "Song A / Song B", 110],       # DJ-mix blend recording
        [1011, "r-k", "Trio Cut", 111],              # 3-artist posse cut
    ])

    # track: id, gid, recording, medium
    _write_tsv(d / "track", [
        [1, "t", 1000, 600], [2, "t", 1001, 600], [3, "t", 1002, 600],
        [4, "t", 1003, 601],   # bootleg medium
        [5, "t", 1004, 600], [6, "t", 1005, 600], [7, "t", 1006, 600],
        [8, "t", 1007, 602],   # interview medium (official release, interview RG)
        [9, "t", 1009, 600],
        [10, "t", 1010, 603],  # DJ-mix medium (official release, DJ-mix RG)
        [11, "t", 1011, 600],  # posse cut on the official album
    ])

    # medium: id, release
    _write_tsv(d / "medium", [[600, 500], [601, 501], [602, 502], [603, 503]])

    # release: id, gid, name, artist_credit, release_group, status
    _write_tsv(d / "release", [
        [500, "rel", "Official Album", 0, 900, 1],   # Official
        [501, "rel", "Bootleg Mashup", 0, 901, 3],   # Bootleg
        [502, "rel", "Interview Disc", 0, 902, 1],   # Official but interview RG
        [503, "rel", "DJ Mix Album", 0, 903, 1],     # Official but DJ-mix RG
    ])

    # release_group: id, gid, name, artist_credit, type  (not read, present for realism)
    _write_tsv(d / "release_group", [
        [900, "rg", "Album", 0, 1], [901, "rg", "Mashup", 0, 1],
        [902, "rg", "Interview", 0, 1], [903, "rg", "Mix", 0, 1],
    ])

    # release_group_secondary_type_join: release_group, secondary_type, created
    _write_tsv(d / "release_group_secondary_type_join", [
        [902, 4, "2020-01-01"],  # 4 = Interview -> excluded
        [903, 8, "2020-01-01"],  # 8 = DJ-mix   -> excluded
    ])


def test_mini_dump_end_to_end(tmp_path):
    dump = tmp_path / "mbdump"
    _build_mini_dump(dump)
    out = tmp_path / "mb.db"

    ingest = mi.MusicBrainzIngest(str(dump))
    stats = ingest.build(seed_mbid="mbid-K", depth=2, out_path=str(out))

    db = CollaborationDatabase(str(out))
    pf = PathFinder(db)

    # Nodes: K, S, Ye, McCartney reachable within depth 2.
    assert db.get_artist_by_name("Kendrick Lamar")
    assert db.get_artist_by_name("SZA")
    assert db.get_artist_by_name("Ye")
    assert db.get_artist_by_name("Paul McCartney")

    # Band-vs-member (KTD9/KTD10): Beatles' only bridge (credit 103) is a
    # BOOTLEG recording -> excluded -> Beatles absent / no connection.
    assert db.get_artist_by_name("The Beatles") is None

    # Interviewer joined only via an Interview release-group -> excluded.
    assert db.get_artist_by_name("Interviewer") is None

    # DJ-mix blend ("Song A / Song B") co-credit is a mixing artifact, not a
    # real collaboration -> the DJ-mix release-group is excluded.
    assert db.get_artist_by_name("Mix Only Artist") is None

    # Solo Guy has no co-credit -> absent. Far Artist is depth 3 -> absent.
    assert db.get_artist_by_name("Solo Guy") is None
    assert db.get_artist_by_name("Far Artist") is None

    # Dangling artist 999 was skipped without aborting the run.
    assert db.get_artist_by_name("Ghost") is None

    # Version dedup: K<->SZA carries the canonical "All the Stars" (the remix
    # collapses into it) plus the distinct "Trio Cut" posse-cut recording.
    k = db.get_artist_by_name("Kendrick Lamar")["id"]
    s = db.get_artist_by_name("SZA")["id"]
    songs = db.get_collaboration_songs(k, s)
    assert "All the Stars" in songs
    assert "All the Stars (Remix)" not in songs  # variant deduped away

    # Full lineup is stored: the "Trio Cut" posse cut lists all 3 artists.
    details = db.get_collaboration_song_details(k, s)
    trio = next(d for d in details if d["name"] == "Trio Cut")
    assert set(trio["collaborators"]) == {"Kendrick Lamar", "SZA", "Ye"}

    # McCartney resolves at degree 2 via Ye (official "All Day").
    p = db.get_artist_by_name("Paul McCartney")["id"]
    conn = pf.find_connection(p, k)
    assert conn is not None
    assert conn["degrees"] == 2
    names = [n["name"] for n in conn["path"]]
    assert names == ["Paul McCartney", "Ye", "Kendrick Lamar"]
    # Every hop carries a connecting song.
    assert all(c["songs"] for c in conn["connections"])


def test_official_filter_can_be_disabled_conceptually(tmp_path):
    # With Bootleg allowed (status set includes '3'), the Beatles bridge appears
    # — proving the filter is what isolates the band, per the U8 finding.
    dump = tmp_path / "mbdump"
    _build_mini_dump(dump)
    out = tmp_path / "mb_all.db"
    # Allow BOTH Official (1) and Bootleg (3): Kendrick's real edges stay AND
    # the bootleg Ye<->Beatles bridge reappears, so Beatles connects.
    ingest = mi.MusicBrainzIngest(str(dump), official_status_ids={"1", "3"})
    ingest.build(seed_mbid="mbid-K", depth=2, out_path=str(out))
    db = CollaborationDatabase(str(out))
    assert db.get_artist_by_name("The Beatles") is not None
