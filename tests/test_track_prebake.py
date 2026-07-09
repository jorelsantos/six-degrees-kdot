"""
Unit tests for the track-ID pre-bake (plan 2026-07-09-001, U4).

Covers R4 plus the adversarial-review fix folded into scope: when an
artist's pre-picked via-song fails to resolve, the pre-bake must retry the
next candidate song on the SAME collaboration edge (not fall back to a
runtime waterfall) and rewire `via_song_id` to whichever song actually
resolves. No network — every search call is injected.
"""

import requests

from database import CollaborationDatabase, NO_TRACK_SENTINEL
from spotify_enrich import RateLimited
from track_prebake import prebake_tracks, resolve_artist_edge

KENDRICK = "kdot"


def _db(tmp_path):
    return CollaborationDatabase(str(tmp_path / "track_prebake.db"))


def _track(tid, name, artists):
    return {"id": tid, "name": name, "artists": [{"name": a} for a in artists]}


def _wire_one_edge(db, artist_id="drake", *songs):
    """kdot <-> artist_id with the given (song_name, collaborators) tuples,
    then a manual path-tree row pointing at the FIRST song as the initial
    via-song (mirroring what U2's shortest-title tie-break would pick when
    the songs are named so the first is shortest)."""
    db.add_artist(KENDRICK, "Kendrick Lamar")
    db.add_artist(artist_id, artist_id.title())
    for name, collabs in songs:
        db.add_collaboration(KENDRICK, artist_id, name, collabs)
    db.refresh_degrees()

    details = db.get_collaboration_song_details(KENDRICK, artist_id)
    first_song_id = next(d["id"] for d in details if d["name"] == songs[0][0])
    db.set_path_tree_bulk([(artist_id, 1, KENDRICK, first_song_id)])
    return details


def test_original_pick_resolves_no_rewire_needed(tmp_path):
    db = _db(tmp_path)
    _wire_one_edge(db, "drake", ("Sing About Me", ["Kendrick Lamar", "Drake"]))

    def fake_search(query, token, timeout):
        return [_track("real-id", "Sing About Me", ["Kendrick Lamar", "Drake"])]

    summary = prebake_tracks(db, token="t", search=fake_search, rate=0)

    assert summary["resolved"] == 1
    assert summary["no_player"] == 0
    row = db.get_path_tree_row("drake")
    songs = db.get_collaboration_song_details(KENDRICK, "drake")
    winning = next(s for s in songs if s["name"] == "Sing About Me")
    assert row["via_song_id"] == winning["id"]  # unchanged
    assert winning["spotify_track_id"] == "real-id"


def test_failed_pick_retries_sibling_song_on_same_edge(tmp_path):
    db = _db(tmp_path)
    _wire_one_edge(
        db, "drake",
        ("Hi", ["Kendrick Lamar", "Drake"]),               # shortest -> original pick
        ("A Much Longer Deep Cut Title", ["Kendrick Lamar", "Drake"]),
    )

    def fake_search(query, token, timeout):
        if query.startswith("Hi "):
            return []  # "Hi" has no Spotify match
        return [_track("sibling-id", "A Much Longer Deep Cut Title",
                       ["Kendrick Lamar", "Drake"])]

    summary = prebake_tracks(db, token="t", search=fake_search, rate=0)

    assert summary["resolved"] == 1
    row = db.get_path_tree_row("drake")
    songs = db.get_collaboration_song_details(KENDRICK, "drake")
    sibling = next(s for s in songs if s["name"] == "A Much Longer Deep Cut Title")
    original = next(s for s in songs if s["name"] == "Hi")
    assert row["via_song_id"] == sibling["id"]  # rewired to the winner
    assert sibling["spotify_track_id"] == "sibling-id"
    # get_collaboration_song_details normalizes both NULL and the sentinel to
    # None, so check the raw column to confirm "Hi" was actually tried and
    # persisted as a miss (not left NULL for an unnecessary re-search).
    with db._get_connection() as conn:
        raw = conn.execute(
            "SELECT spotify_track_id FROM songs WHERE id = ?", (original["id"],)
        ).fetchone()[0]
    assert raw == NO_TRACK_SENTINEL


def test_all_candidates_exhausted_leaves_no_player(tmp_path):
    db = _db(tmp_path)
    _wire_one_edge(
        db, "drake",
        ("Hi", ["Kendrick Lamar", "Drake"]),
        ("Also No Match", ["Kendrick Lamar", "Drake"]),
    )

    def fake_search(query, token, timeout):
        return []  # nothing ever matches

    summary = prebake_tracks(db, token="t", search=fake_search, rate=0)

    assert summary["resolved"] == 0
    assert summary["no_player"] == 1
    row = db.get_path_tree_row("drake")
    songs = db.get_collaboration_song_details(KENDRICK, "drake")
    assert all(s["spotify_track_id"] is None for s in songs)  # sentinel normalizes to None
    # via_song_id untouched (still points at the original shortest-title pick)
    original = next(s for s in songs if s["name"] == "Hi")
    assert row["via_song_id"] == original["id"]


def test_fully_resolved_artist_is_not_a_candidate(tmp_path):
    """Once the CURRENT via-song already carries a real id, the artist is
    excluded at the SQL candidate query itself (get_artists_needing_track_ids)
    — the cheapest possible resumability check, before resolve_artist_edge
    ever runs."""
    db = _db(tmp_path)
    details = _wire_one_edge(db, "drake", ("Hi", ["Kendrick Lamar", "Drake"]))
    song_id = details[0]["id"]
    db.set_spotify_track_id(song_id, "already-there")

    assert db.get_artists_needing_track_ids() == []

    calls = []

    def counting_search(query, token, timeout):
        calls.append(query)
        return []

    summary = prebake_tracks(db, token="t", search=counting_search, rate=0)

    assert calls == []
    assert summary["candidates"] == 0
    assert summary["processed"] == 0


def test_resolve_artist_edge_skips_network_for_an_already_resolved_sibling(tmp_path):
    """Defense-in-depth on resolve_artist_edge itself (not just the SQL
    filter): if the first-tried song in edge order already carries a real
    id — e.g. resolved by an earlier partial run — it must win immediately
    without a network call, even when called directly."""
    db = _db(tmp_path)
    details = _wire_one_edge(
        db, "drake",
        ("Hi", ["Kendrick Lamar", "Drake"]),
        ("Second", ["Kendrick Lamar", "Drake"]),
    )
    hi = next(d for d in details if d["name"] == "Hi")
    hi["spotify_track_id"] = "already-there"  # simulate a pre-resolved sibling

    calls = []

    def counting_search(query, token, timeout):
        calls.append(query)
        return [_track("should-not-be-used", "Second", ["Kendrick Lamar", "Drake"])]

    winner, sentinels = resolve_artist_edge(details, "t", search=counting_search)

    assert calls == []  # short-circuited on "Hi" before ever searching
    assert winner == (hi["id"], "already-there")
    assert sentinels == []


def test_already_sentinel_song_skips_to_next_candidate_without_network_call(tmp_path):
    db = _db(tmp_path)
    _wire_one_edge(
        db, "drake",
        ("Hi", ["Kendrick Lamar", "Drake"]),
        ("Sibling Song", ["Kendrick Lamar", "Drake"]),
    )
    songs = db.get_collaboration_song_details(KENDRICK, "drake")
    hi_id = next(s["id"] for s in songs if s["name"] == "Hi")
    db.set_spotify_track_id(hi_id, NO_TRACK_SENTINEL)  # pretend a prior run already tried "Hi"

    calls = []

    def counting_search(query, token, timeout):
        calls.append(query)
        return [_track("sib-id", "Sibling Song", ["Kendrick Lamar", "Drake"])]

    summary = prebake_tracks(db, token="t", search=counting_search, rate=0)

    assert len(calls) == 1  # only the sibling was searched; "Hi" was skipped for free
    assert summary["resolved"] == 1


def test_rate_limit_aborts_whole_run_and_preserves_prior_progress(tmp_path):
    db = _db(tmp_path)
    _wire_one_edge(db, "drake", ("Sing About Me", ["Kendrick Lamar", "Drake"]))
    db.add_artist("sza", "SZA")
    db.add_collaboration(KENDRICK, "sza", "All The Stars", ["Kendrick Lamar", "SZA"])
    db.refresh_degrees()
    sza_songs = db.get_collaboration_song_details(KENDRICK, "sza")
    db.set_path_tree_bulk([("sza", 1, KENDRICK, sza_songs[0]["id"])])
    db.set_popularity_bulk([(KENDRICK, 100)])  # both share predecessor kdot -> tie on priority

    calls = {"n": 0}

    def flaky(query, token, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_track("first-id", "placeholder", ["x"])]
        raise RateLimited(retry_after=2.0)

    summary = prebake_tracks(db, token="t", search=flaky, rate=0)

    assert summary["aborted"] == 1
    assert summary["processed"] == 1  # only the first artist committed


def test_transient_error_leaves_artist_for_retry(tmp_path):
    db = _db(tmp_path)
    _wire_one_edge(db, "drake", ("Sing About Me", ["Kendrick Lamar", "Drake"]))

    def boom(query, token, timeout):
        raise requests.RequestException("timeout")

    summary = prebake_tracks(db, token="t", search=boom, rate=0)

    assert summary["errors"] == 1
    assert summary["processed"] == 0
    # Still a candidate for a later run.
    assert len(db.get_artists_needing_track_ids()) == 1


def test_priority_orders_by_predecessor_popularity(tmp_path):
    db = _db(tmp_path)
    db.add_artist(KENDRICK, "Kendrick Lamar")
    db.add_artist("hub_a", "Hub A")
    db.add_artist("hub_b", "Hub B")
    db.add_artist("child_a", "Child A")
    db.add_artist("child_b", "Child B")
    db.add_collaboration(KENDRICK, "hub_a", "Song 1")
    db.add_collaboration(KENDRICK, "hub_b", "Song 2")
    db.add_collaboration("hub_a", "child_a", "Song 3", ["Hub A", "Child A"])
    db.add_collaboration("hub_b", "child_b", "Song 4", ["Hub B", "Child B"])
    db.refresh_degrees()
    db.set_popularity_bulk([("hub_a", 10), ("hub_b", 90)])

    songs_a = db.get_collaboration_song_details("hub_a", "child_a")
    songs_b = db.get_collaboration_song_details("hub_b", "child_b")
    db.set_path_tree_bulk([
        ("child_a", 2, "hub_a", songs_a[0]["id"]),
        ("child_b", 2, "hub_b", songs_b[0]["id"]),
    ])

    order = [c["artist_id"] for c in db.get_artists_needing_track_ids()]
    assert order == ["child_b", "child_a"]  # hub_b (90) outranks hub_a (10)


def test_resolve_artist_edge_calls_pace_once_per_network_search(tmp_path):
    db = _db(tmp_path)
    details = _wire_one_edge(
        db, "drake",
        ("Hi", ["Kendrick Lamar", "Drake"]),
        ("Second", ["Kendrick Lamar", "Drake"]),
    )
    calls = []

    def fake_search(query, token, timeout):
        return []  # both miss -> both should trigger a pace() call

    winner, sentinels = resolve_artist_edge(
        details, "t", search=fake_search, pace=lambda: calls.append(1))

    assert winner is None
    assert len(sentinels) == 2
    assert len(calls) == 2


def test_seed_ids_restricts_to_exactly_that_set(tmp_path):
    """A demo (U5) needs its showcase chain's hops force-resolved regardless
    of where they'd fall in the predecessor-popularity priority queue."""
    db = _db(tmp_path)
    _wire_one_edge(db, "drake", ("Sing About Me", ["Kendrick Lamar", "Drake"]))
    db.add_artist("sza", "SZA")
    db.add_collaboration(KENDRICK, "sza", "All The Stars", ["Kendrick Lamar", "SZA"])
    db.refresh_degrees()
    sza_songs = db.get_collaboration_song_details(KENDRICK, "sza")
    db.set_path_tree_bulk([("sza", 1, KENDRICK, sza_songs[0]["id"])])

    def fake_search(query, token, timeout):
        return [_track("id", "Sing About Me", ["Kendrick Lamar", "Drake"])]

    summary = prebake_tracks(db, token="t", search=fake_search, rate=0,
                             artist_ids=["drake"])

    assert summary["candidates"] == 1
    assert summary["resolved"] == 1
    # "sza" was never touched — outside the seed set.
    assert len(db.get_artists_needing_track_ids()) == 1
