"""
Unit tests for the popularity-enrichment pass (U1).

Covers the resumable-marking + Last.fm/degree fallback logic without touching
the network — the Last.fm fetch is injected. Covers R2.
"""

import requests

from database import CollaborationDatabase
from popularity_enrich import enrich


def _db(tmp_path):
    db = CollaborationDatabase(str(tmp_path / "enrich.db"))
    return db


def _wire_graph(db):
    """Small graph: Carey is a hub (degree 3), Scientist mid (2), Adigun tail (1)."""
    for aid, name in [("carey", "Mariah Carey"), ("scientist", "Mariah the Scientist"),
                      ("adigun", "Mariah Adigun"), ("x", "X"), ("y", "Y")]:
        db.add_artist(aid, name)
    db.add_collaboration("carey", "x", "Song A")
    db.add_collaboration("carey", "y", "Song B")
    db.add_collaboration("carey", "scientist", "Song C")
    db.add_collaboration("scientist", "x", "Song D")
    db.add_collaboration("adigun", "y", "Song E")


def _pop(db, artist_id):
    return db.get_artist(artist_id)["popularity"]


def test_lastfm_value_stored_and_marked(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)

    def fake_fetch(mbid, api_key, timeout):
        return {"carey": 3_430_494, "scientist": 25_315}.get(mbid)

    summary = enrich(db, api_key="k", fetch=fake_fetch, rate=0)

    assert _pop(db, "carey") == 3_430_494
    assert _pop(db, "scientist") == 25_315
    assert summary["lastfm"] == 2
    # Everyone processed is marked enriched -> a re-run does nothing.
    assert db.get_unenriched_artists() == []


def test_no_match_falls_back_to_degree(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)

    # Last.fm knows nobody -> everyone gets their graph-degree.
    summary = enrich(db, api_key="k", fetch=lambda *a: None, rate=0)

    assert _pop(db, "carey") == 3      # hub degree
    assert _pop(db, "adigun") == 1     # tail degree
    assert summary["degree_fallback"] == 5
    assert summary["lastfm"] == 0


def test_network_error_degrades_not_crashes(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)

    def boom(mbid, api_key, timeout):
        raise requests.RequestException("timeout")

    summary = enrich(db, api_key="k", fetch=boom, rate=0)
    # Run completes; failed lookups fall back to degree.
    assert summary["processed"] == 5
    assert summary["degree_fallback"] == 5
    assert _pop(db, "carey") == 3


def test_resumable_skips_already_enriched(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)

    calls = []

    def counting_fetch(mbid, api_key, timeout):
        calls.append(mbid)
        return 100

    enrich(db, api_key="k", fetch=counting_fetch, rate=0)
    first = len(calls)
    # Second run: nothing left un-enriched, so no further fetches.
    enrich(db, api_key="k", fetch=counting_fetch, rate=0)
    assert len(calls) == first == 5


def test_min_degree_filter_skips_tail(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)

    summary = enrich(db, api_key=None, min_degree=2, fetch=lambda *a: None, rate=0)

    # Carey (3) and Scientist (2) qualify; Adigun (1), X (2? -> X has 2), Y (2? ) ...
    # X edges: carey-x, scientist-x = 2; Y edges: carey-y, adigun-y = 2.
    # So only Adigun (degree 1) is below the threshold.
    assert summary["skipped_below_min_degree"] == 1
    assert summary["processed"] == 4
    # Adigun left un-enriched for a later full pass.
    remaining = [a["id"] for a in db.get_unenriched_artists()]
    assert remaining == ["adigun"]


def test_no_api_key_uses_degree_for_all(tmp_path):
    db = _db(tmp_path)
    _wire_graph(db)

    summary = enrich(db, api_key=None, rate=0)
    assert summary["lastfm"] == 0
    assert summary["degree_fallback"] == 5
    assert _pop(db, "carey") == 3
