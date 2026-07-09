"""
Unit tests for the Cloudflare D1 serving-DB export (plan 2026-07-09-001, U6).

Covers R6: the exported slim DB answers a connection walk identically to the
master DB's path tree, the FTS5 setup SQL (applied post-import, per the D1
virtual-table import gotcha) makes artists searchable by name and alias, and
the two sentinel-cleaning rules differ by column exactly as documented
(photo_url collapses to NULL; via_track_id's sentinel passes through so the
Worker's lazy resolve can tell "confirmed miss" from "never checked").
"""

import sqlite3

from database import CollaborationDatabase, NO_TRACK_SENTINEL, PHOTO_NONE_SENTINEL
from export_serving_db import FTS5_SETUP_SQL, build_serving_db

KENDRICK = "kdot"


def _db(tmp_path):
    return CollaborationDatabase(str(tmp_path / "master.db"))


def _wire_chain(db):
    for aid, name in [(KENDRICK, "Kendrick Lamar"), ("drake", "Drake"), ("future", "Future")]:
        db.add_artist(aid, name)
    db.add_collaboration(KENDRICK, "drake", "Sing About Me", ["Kendrick Lamar", "Drake"])
    db.add_collaboration("drake", "future", "Jumpman", ["Drake", "Future"])
    db.refresh_degrees()
    db.add_artist_alias("drake", "Drizzy")

    def song_id(a, b, name):
        return next(s["id"] for s in db.get_collaboration_song_details(a, b) if s["name"] == name)

    db.set_path_tree_bulk([
        (KENDRICK, 0, None, None),
        ("drake", 1, KENDRICK, song_id(KENDRICK, "drake", "Sing About Me")),
        ("future", 2, "drake", song_id("drake", "future", "Jumpman")),
    ])


def test_via_song_collaborators_exported_for_the_resolve_track_accept_guard(tmp_path):
    """The Worker's lazy resolve-track endpoint needs the full credited
    lineup (not just the two chain endpoints) to safely apply the same
    title+artist accept-guard as the offline pre-bake."""
    import json

    db = _db(tmp_path)
    _wire_chain(db)
    out = tmp_path / "serving.db"

    build_serving_db(db, out)

    conn = sqlite3.connect(str(out))
    row = conn.execute(
        "SELECT via_song_collaborators FROM artists WHERE id = ?", ("drake",)
    ).fetchone()
    assert json.loads(row[0]) == ["Kendrick Lamar", "Drake"]


def test_serving_db_answers_connection_walk_identically(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    out = tmp_path / "serving.db"

    build_serving_db(db, out)

    conn = sqlite3.connect(str(out))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM artists WHERE id = ?", ("future",)).fetchone()
    assert row["kendrick_distance"] == 2
    assert row["predecessor_id"] == "drake"
    assert row["via_song_title"] == "Jumpman"

    # Full walk to Kendrick matches the master DB's path tree.
    steps = []
    current = "future"
    while current is not None:
        r = conn.execute("SELECT predecessor_id FROM artists WHERE id = ?", (current,)).fetchone()
        steps.append(current)
        current = r["predecessor_id"]
    assert steps == ["future", "drake", KENDRICK]


def test_fts5_setup_finds_artist_by_name_and_alias(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    out = tmp_path / "serving.db"
    build_serving_db(db, out)

    conn = sqlite3.connect(str(out))
    conn.executescript(FTS5_SETUP_SQL)

    by_name = conn.execute(
        "SELECT DISTINCT artist_id FROM search_fts WHERE term MATCH 'kendrick*'"
    ).fetchall()
    assert (KENDRICK,) in by_name

    by_alias = conn.execute(
        "SELECT DISTINCT artist_id FROM search_fts WHERE term MATCH 'drizzy'"
    ).fetchall()
    assert ("drake",) in by_alias


def test_photo_sentinel_collapses_to_null(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    db.set_photo_urls_bulk([("drake", PHOTO_NONE_SENTINEL)])
    out = tmp_path / "serving.db"

    build_serving_db(db, out)

    conn = sqlite3.connect(str(out))
    row = conn.execute("SELECT photo_url FROM artists WHERE id = ?", ("drake",)).fetchone()
    assert row[0] is None  # NOT the raw "none" string


def test_track_id_sentinel_passes_through_unchanged(tmp_path):
    """Unlike photo_url, the track-id sentinel must survive the export as-is
    -- the Worker's lazy resolve endpoint needs to distinguish a confirmed
    miss (skip resolving) from a never-checked NULL (may still resolve)."""
    db = _db(tmp_path)
    _wire_chain(db)
    sid = next(
        s["id"] for s in db.get_collaboration_song_details(KENDRICK, "drake")
        if s["name"] == "Sing About Me"
    )
    db.set_spotify_track_id(sid, NO_TRACK_SENTINEL)
    out = tmp_path / "serving.db"

    build_serving_db(db, out)

    conn = sqlite3.connect(str(out))
    row = conn.execute("SELECT via_track_id FROM artists WHERE id = ?", ("drake",)).fetchone()
    assert row[0] == NO_TRACK_SENTINEL  # NOT collapsed to NULL


def test_unreached_artist_exports_with_null_distance(tmp_path):
    db = _db(tmp_path)
    _wire_chain(db)
    db.add_artist("island", "Islander")  # no path-tree row at all
    out = tmp_path / "serving.db"

    build_serving_db(db, out)

    conn = sqlite3.connect(str(out))
    row = conn.execute("SELECT kendrick_distance, predecessor_id FROM artists WHERE id = ?",
                       ("island",)).fetchone()
    assert row[0] is None
    assert row[1] is None


def test_rerun_fully_overwrites_the_serving_db(tmp_path):
    """A re-export must reflect the CURRENT master DB state, not merge with
    a stale prior export (KTD6: re-import is cheap and repeatable)."""
    db = _db(tmp_path)
    _wire_chain(db)
    out = tmp_path / "serving.db"
    build_serving_db(db, out)

    db.add_artist("newcomer", "Newcomer")
    count = build_serving_db(db, out)

    conn = sqlite3.connect(str(out))
    total = conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    assert total == count == 4  # kdot, drake, future, newcomer -- no duplicates
