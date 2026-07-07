"""
Unit tests for the Spotify track-id enrichment pass (plan 2026-07-06-004, U1).

Covers the accept / sentinel / resume logic and the graceful-degrade paths
without touching the network — the search call is injected (mirrors
test_popularity_enrich's `fetch` seam). Covers R2 (a second run makes zero
search calls).
"""

import requests

from database import CollaborationDatabase, NO_TRACK_SENTINEL
from spotify_enrich import enrich, RateLimited


def _db(tmp_path):
    return CollaborationDatabase(str(tmp_path / "spotify_enrich.db"))


def _wire(db):
    """Two connecting songs on distinct edges."""
    db.add_artist("a", "Mariah the Scientist")
    db.add_artist("b", "Friday")
    db.add_artist("c", "Metro Boomin")
    db.add_artist("d", "Future")
    db.add_collaboration("a", "b", "Slow Down", ["Friday", "Mariah the Scientist"])
    db.add_collaboration("c", "d", "Like That", ["Metro Boomin", "Future"])
    db.refresh_degrees()


def _track(tid, name, artists):
    return {"id": tid, "name": name, "artists": [{"name": a} for a in artists]}


def _track_id_for(db, a1, a2, song_name):
    details = db.get_collaboration_song_details(a1, a2)
    return next(d["spotify_track_id"] for d in details if d["name"] == song_name)


def test_title_artist_match_stores_track_id(tmp_path):
    db = _db(tmp_path)
    _wire(db)

    def fake_search(query, token, timeout):
        if "Slow Down" in query:
            return [_track("4LycrPCWsqESQ08I3ghkrT", "Slow Down",
                           ["Friday", "Mariah the Scientist"])]
        return [_track("likethatID", "Like That", ["Metro Boomin", "Future"])]

    summary = enrich(db, token="t", search=fake_search, rate=0)

    assert summary["resolved"] == 2
    assert summary["sentinel"] == 0
    assert _track_id_for(db, "a", "b", "Slow Down") == "4LycrPCWsqESQ08I3ghkrT"


def test_wrong_artist_stores_sentinel_not_wrong_id(tmp_path):
    db = _db(tmp_path)
    _wire(db)

    # Same title, unrelated artist -> must be rejected, sentinel stored.
    def fake_search(query, token, timeout):
        return [_track("WRONG", "Slow Down", ["Selena Gomez"]),
                _track("ALSO_WRONG", "Slow Down", ["Bobby Valentino"])]

    summary = enrich(db, token="t", search=fake_search, rate=0)

    assert summary["resolved"] == 0
    assert summary["sentinel"] == 2
    # Stored value is the sentinel; get_collaboration_song_details normalizes it
    # to None so the UI degrades gracefully.
    assert _track_id_for(db, "a", "b", "Slow Down") is None
    with db._get_connection() as conn:
        raw = conn.execute(
            "SELECT spotify_track_id FROM songs WHERE song_name = 'Slow Down'"
        ).fetchone()[0]
    assert raw == NO_TRACK_SENTINEL


def test_network_error_leaves_song_for_retry(tmp_path):
    db = _db(tmp_path)
    _wire(db)

    def boom(query, token, timeout):
        raise requests.RequestException("timeout")

    summary = enrich(db, token="t", search=boom, rate=0)

    # Run completes; both songs left NULL (not the sentinel) for a later retry.
    assert summary["errors"] == 2
    assert summary["processed"] == 0
    assert len(db.get_songs_without_track_id()) == 2


def test_429_aborts_cleanly_leaving_rows_null(tmp_path):
    db = _db(tmp_path)
    _wire(db)

    calls = []

    def rate_limited(query, token, timeout):
        calls.append(query)
        if len(calls) == 1:
            return [_track("firstID", "Slow Down", ["Friday", "Mariah the Scientist"])]
        raise RateLimited(retry_after=1.0)

    summary = enrich(db, token="t", search=rate_limited, rate=0)

    assert summary["aborted"] == 1
    assert summary["processed"] == 1  # only the first song committed
    # The un-processed song stays NULL and is picked up on resume.
    assert len(db.get_songs_without_track_id()) == 1


def test_rerun_makes_zero_search_calls(tmp_path):
    db = _db(tmp_path)
    _wire(db)

    calls = []

    def counting(query, token, timeout):
        calls.append(query)
        return [_track("id-" + str(len(calls)), "Slow Down",
                       ["Friday", "Mariah the Scientist", "Metro Boomin", "Future"])]

    enrich(db, token="t", search=counting, rate=0)
    first = len(calls)
    assert first == 2
    # Second run: everything resolved -> zero further search calls (R2).
    enrich(db, token="t", search=counting, rate=0)
    assert len(calls) == first


def test_song_details_expose_track_id(tmp_path):
    db = _db(tmp_path)
    _wire(db)

    def fake_search(query, token, timeout):
        if "Slow Down" in query:
            return [_track("slowID", "Slow Down", ["Friday", "Mariah the Scientist"])]
        return []  # "Like That" -> no candidates -> sentinel

    enrich(db, token="t", search=fake_search, rate=0)

    assert _track_id_for(db, "a", "b", "Slow Down") == "slowID"
    assert _track_id_for(db, "c", "d", "Like That") is None  # sentinel -> None


def test_min_degree_bounds_the_pass(tmp_path):
    db = _db(tmp_path)
    db.add_artist("hub", "Hub")
    db.add_artist("x", "X")
    db.add_artist("y", "Y")
    db.add_artist("tail1", "Tail One")
    db.add_artist("tail2", "Tail Two")
    # Hub reaches degree 2; the tail edge touches only degree-1 artists.
    db.add_collaboration("hub", "x", "Hub Song A", ["Hub", "X"])
    db.add_collaboration("hub", "y", "Hub Song B", ["Hub", "Y"])
    db.add_collaboration("tail1", "tail2", "Tail Song", ["Tail One", "Tail Two"])
    db.refresh_degrees()

    # min_degree=2: only songs on an edge touching Hub (degree 2) qualify.
    eligible = db.get_songs_without_track_id(min_degree=2)
    names = sorted(s["song_name"] for s in eligible)
    assert names == ["Hub Song A", "Hub Song B"]
