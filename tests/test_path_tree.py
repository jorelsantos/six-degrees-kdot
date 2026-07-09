"""
Unit tests for the path-tree precompute (plan 2026-07-09-001, U2).

Covers R2: every artist row's precomputed distance/predecessor/via-song must
agree with the live BFS oracle (PathFinder), Kendrick himself must be the
unique distance-0 root, unreachable artists must stay NULL, and the
full-table invariants (predecessor-at-distance-minus-one, via-song-belongs-
to-edge) must actually catch corruption.
"""

import pytest

from database import CollaborationDatabase
from path_finder_sqlite import PathFinder
from path_tree import (
    KendrickNotFoundError,
    compute_path_tree,
    persist_path_tree,
    resolve_kendrick_id,
    validate,
)

KENDRICK = "kdot"


def _db(tmp_path, name="tree.db"):
    return CollaborationDatabase(str(tmp_path / name))


def _wire_graph(db):
    """
    kdot -- drake -- future -- ghost (degrees 0,1,2,3)
    kdot -- sza (degree 1, alternate route to drake's neighborhood)
    sza -- drake (so drake has two frontier candidates at distance 1: kdot
    directly, making drake distance 1 via kdot; sza is also distance 1)
    island: nobody connects to it -> unreachable.
    """
    for aid, name in [
        (KENDRICK, "Kendrick Lamar"),
        ("drake", "Drake"),
        ("sza", "SZA"),
        ("future", "Future"),
        ("ghost", "Ghostwriter"),
        ("island", "Islander"),
    ]:
        db.add_artist(aid, name)
    db.add_collaboration(KENDRICK, "drake", "Sing About Me")
    db.add_collaboration(KENDRICK, "sza", "All The Stars")
    db.add_collaboration("drake", "future", "Jumpman")
    db.add_collaboration("future", "ghost", "Some Deep Cut")
    # island has no edges at all.


def _set_popularity(db, values):
    db.set_popularity_bulk(list(values.items()))


def test_kendrick_is_unique_distance_zero_root(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    row = db.get_path_tree_row(KENDRICK)
    assert row["kendrick_distance"] == 0
    assert row["predecessor_id"] is None
    assert row["via_song_id"] is None


def test_unreachable_artist_stays_null(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    row = db.get_path_tree_row("island")
    assert row["kendrick_distance"] is None
    assert row["predecessor_id"] is None
    assert row["via_song_id"] is None


def test_distances_agree_with_live_bfs_for_every_reachable_artist(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    finder = PathFinder(db)
    for artist_id in ["drake", "sza", "future", "ghost"]:
        live_path = finder.find_path(artist_id, KENDRICK)
        live_distance = len(live_path) - 1
        row = db.get_path_tree_row(artist_id)
        assert row["kendrick_distance"] == live_distance, artist_id


def test_predecessor_walk_terminates_at_kendrick_in_exactly_distance_steps(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    row = db.get_path_tree_row("ghost")
    assert row["kendrick_distance"] == 3

    steps = 0
    current = "ghost"
    while current != KENDRICK:
        current = db.get_path_tree_row(current)["predecessor_id"]
        steps += 1
        assert steps <= 10  # guard against an infinite loop on a bug
    assert steps == 3


def test_every_predecessor_pair_is_a_real_collaboration_edge(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    edge_songs = db.get_all_edge_songs()
    for artist_id, (dist, pred, song) in tree.items():
        if artist_id == KENDRICK or dist is None:
            continue
        key = (pred, artist_id) if pred < artist_id else (artist_id, pred)
        assert key in edge_songs, f"{artist_id}'s predecessor {pred} has no edge"
        assert song in {s["id"] for s in edge_songs[key]}


def test_predecessor_tiebreak_prefers_higher_popularity(tmp_path):
    """drake is reachable both directly from kdot AND via sza-drake in the
    same BFS round is not possible here (drake is distance 1 either way via
    direct edge) — instead test the tie-break where two DIFFERENT frontier
    nodes could reach the SAME new node: give future two routes.
    """
    db = _db(tmp_path)
    for aid, name in [(KENDRICK, "Kendrick Lamar"), ("a", "A"), ("b", "B"), ("target", "Target")]:
        db.add_artist(aid, name)
    db.add_collaboration(KENDRICK, "a", "Song A")
    db.add_collaboration(KENDRICK, "b", "Song B")
    db.add_collaboration("a", "target", "Song C")
    db.add_collaboration("b", "target", "Song D")
    _set_popularity(db, {"a": 10, "b": 90})

    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    row = db.get_path_tree_row("target")
    assert row["kendrick_distance"] == 2
    assert row["predecessor_id"] == "b"  # higher popularity wins


def test_via_song_prefers_shortest_title(tmp_path):
    db = _db(tmp_path)
    db.add_artist(KENDRICK, "Kendrick Lamar")
    db.add_artist("drake", "Drake")
    db.add_collaboration(KENDRICK, "drake", "A Very Long Extended Title Remix")
    db.add_collaboration(KENDRICK, "drake", "Hi")

    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    row = db.get_path_tree_row("drake")
    songs = db.get_collaboration_song_details(KENDRICK, "drake")
    short_song = next(s for s in songs if s["name"] == "Hi")
    assert row["via_song_id"] == short_song["id"]


def test_resolve_kendrick_id_raises_when_not_found(tmp_path):
    db = _db(tmp_path)
    db.add_artist("someone", "Someone Else")
    with pytest.raises(KendrickNotFoundError):
        resolve_kendrick_id(db)


def test_resolve_kendrick_id_honors_explicit_override(tmp_path):
    db = _db(tmp_path)
    db.add_artist("xyz", "Whoever")
    assert resolve_kendrick_id(db, override="xyz") == "xyz"


def test_validate_passes_on_a_correct_tree(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    problems = validate(db, KENDRICK, sample_size=10)
    assert problems == []


def test_validate_catches_predecessor_distance_corruption(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    # Corrupt: drake's distance says 1, but bump it to 5 without touching its
    # predecessor's actual distance -- the invariant must catch the mismatch.
    db.set_path_tree_bulk([("drake", 5, KENDRICK, None)])

    problems = validate(db, KENDRICK, sample_size=10)
    assert any("drake" in p for p in problems)


def test_validate_catches_via_song_from_wrong_edge(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    # Corrupt: point drake's via_song at a song id that belongs to a
    # different edge (future<->ghost).
    ghost_songs = db.get_collaboration_song_details("future", "ghost")
    wrong_song_id = ghost_songs[0]["id"]
    db.set_path_tree_bulk([("drake", 1, KENDRICK, wrong_song_id)])

    problems = validate(db, KENDRICK, sample_size=10)
    assert any("does not belong to the" in p for p in problems)


def test_validate_catches_more_than_one_zero_distance_row(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)
    tree = compute_path_tree(db, KENDRICK)
    persist_path_tree(db, tree)

    db.set_path_tree_bulk([("drake", 0, None, None)])

    problems = validate(db, KENDRICK, sample_size=10)
    assert any("exactly one distance-0 row" in p for p in problems)
