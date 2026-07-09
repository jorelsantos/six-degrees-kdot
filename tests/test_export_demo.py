"""
Unit tests for the Tier A static demo exporter (plan 2026-07-09-001, U5).

Covers R5: the exporter walks a precomputed path tree into the JSON shape
the demo frontend renders, degrades sentinels to null (photo/track), and
skips (without crashing the whole export) an artist whose chain isn't baked
yet.
"""

import json

from database import CollaborationDatabase, NO_TRACK_SENTINEL, PHOTO_NONE_SENTINEL
from export_demo import build_chain, export_demo

KENDRICK = "kdot"


def _db(tmp_path):
    return CollaborationDatabase(str(tmp_path / "export_demo.db"))


def _wire_chain(db):
    """kdot <-> drake <-> future <-> ghost (distances 0,1,2,3)."""
    for aid, name in [
        (KENDRICK, "Kendrick Lamar"), ("drake", "Drake"),
        ("future", "Future"), ("ghost", "Ghostwriter"),
    ]:
        db.add_artist(aid, name)
    db.add_collaboration(KENDRICK, "drake", "Sing About Me", ["Kendrick Lamar", "Drake"])
    db.add_collaboration("drake", "future", "Jumpman", ["Drake", "Future"])
    db.add_collaboration("future", "ghost", "Some Deep Cut", ["Future", "Ghostwriter"])
    db.refresh_degrees()

    def song_id(a, b, name):
        return next(s["id"] for s in db.get_collaboration_song_details(a, b) if s["name"] == name)

    db.set_path_tree_bulk([
        (KENDRICK, 0, None, None),
        ("drake", 1, KENDRICK, song_id(KENDRICK, "drake", "Sing About Me")),
        ("future", 2, "drake", song_id("drake", "future", "Jumpman")),
        ("ghost", 3, "future", song_id("future", "ghost", "Some Deep Cut")),
    ])


def test_build_chain_for_a_distance_three_artist(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    db.set_photo_urls_bulk([
        ("ghost", "https://commons.wikimedia.org/wiki/Special:FilePath/g.jpg"),
        ("future", "https://commons.wikimedia.org/wiki/Special:FilePath/f.jpg"),
    ])
    db.set_spotify_track_id_bulk([
        (song_id_for(db, "future", "ghost", "Some Deep Cut"), "real-id"),
    ])

    chain = build_chain(db, "ghost")

    assert chain["degrees"] == 3
    assert [p["name"] for p in chain["path"]] == ["Ghostwriter", "Future", "Drake", "Kendrick Lamar"]
    assert len(chain["hops"]) == 3
    assert chain["hops"][0]["song_name"] == "Some Deep Cut"
    assert chain["hops"][0]["track_id"] == "real-id"


def song_id_for(db, a, b, name):
    return next(s["id"] for s in db.get_collaboration_song_details(a, b) if s["name"] == name)


def test_photo_none_sentinel_degrades_to_null(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    db.set_photo_urls_bulk([("drake", PHOTO_NONE_SENTINEL)])

    chain = build_chain(db, "drake")

    drake_node = next(p for p in chain["path"] if p["id"] == "drake")
    assert drake_node["photo_url"] is None


def test_no_track_sentinel_degrades_to_null(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    sid = song_id_for(db, KENDRICK, "drake", "Sing About Me")
    db.set_spotify_track_id(sid, NO_TRACK_SENTINEL)

    chain = build_chain(db, "drake")

    assert chain["hops"][0]["track_id"] is None
    assert chain["hops"][0]["song_name"] == "Sing About Me"  # title still shows


def test_export_writes_one_file_per_artist_and_an_index(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    showcase = [{"name": "Drake", "id": "drake"}, {"name": "Ghostwriter", "id": "ghost"}]

    index = export_demo(db, showcase, tmp_path / "out")

    assert len(index) == 2
    assert (tmp_path / "out" / "drake.json").exists()
    assert (tmp_path / "out" / "ghost.json").exists()
    written_index = json.loads((tmp_path / "out" / "index.json").read_text())
    assert {e["id"] for e in written_index} == {"drake", "ghost"}
    drake_json = json.loads((tmp_path / "out" / "drake.json").read_text())
    assert drake_json["degrees"] == 1


def test_export_skips_unbaked_artist_without_crashing(tmp_path, capsys):
    db = _db(tmp_path)
    _wire_chain(db)
    db.add_artist("unbaked", "Unbaked Artist")  # exists, but no path-tree row
    showcase = [{"name": "Drake", "id": "drake"}, {"name": "Unbaked Artist", "id": "unbaked"}]

    index = export_demo(db, showcase, tmp_path / "out")

    assert len(index) == 1
    assert index[0]["id"] == "drake"
    assert "unbaked" not in {e["id"] for e in index}
