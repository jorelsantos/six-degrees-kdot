"""
Unit tests for the offline photo pre-bake (plan 2026-07-09-001, U3).

Covers R3: the three-stage bulk order (Wikidata batch -> Deezer -> TheAudioDB
tail), tri-state persistence (URL / "none" sentinel / retryable NULL), resume
behavior, and the whole-run 429 abort. No network — every fetcher is a fake
seeded through artist_photo's injectable stage functions via monkeypatch.
"""

import requests

import artist_photo
import photo_prebake
from database import CollaborationDatabase, PHOTO_NONE_SENTINEL
from photo_prebake import prebake

WD_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/A.jpg?width=320"
DZ_URL = "https://e-cdns-images.dzcdn.net/images/artist/x/1000x1000.jpg"
ADB_URL = "https://r2.theaudiodb.com/images/media/artist/thumb/a.jpg"


def _db(tmp_path, name="prebake.db"):
    db = CollaborationDatabase(str(tmp_path / name))
    return db


def _wire_artists(db, ids_names):
    for aid, name in ids_names:
        db.add_artist(aid, name)
    # give everyone degree >= 1 so the default min_degree=0 filter includes them
    db.add_collaboration(ids_names[0][0], ids_names[-1][0], "Connective Tissue")


class _HTTPError429(requests.HTTPError):
    def __init__(self):
        resp = requests.Response()
        resp.status_code = 429
        super().__init__("429", response=resp)


def test_wikidata_hit_short_circuits_later_stages(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _wire_artists(db, [("a", "Artist A"), ("b", "Artist B")])

    monkeypatch.setattr(
        photo_prebake, "resolve_wikidata_batch",
        lambda mbids, timeout=None: {"a": WD_URL, "b": WD_URL},
    )
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))

    summary = prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    assert summary["wikidata_hits"] == 2
    assert db.get_photo_urls(["a", "b"]) == {"a": WD_URL, "b": WD_URL}


def test_deezer_fills_wikidata_miss(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _wire_artists(db, [("a", "Artist A"), ("b", "Artist B")])

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", lambda mbids, timeout=None: {})
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: DZ_URL)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))

    summary = prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    assert summary["deezer_hits"] == 2
    assert db.get_photo_urls(["a", "b"]) == {"a": DZ_URL, "b": DZ_URL}


def test_theaudiodb_fills_the_remaining_tail(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _wire_artists(db, [("a", "Artist A")])

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", lambda mbids, timeout=None: {})
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: None)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single", lambda mbid, timeout=None: ADB_URL)

    summary = prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    assert summary["theaudiodb_hits"] == 1
    assert db.get_photo_urls(["a"]) == {"a": ADB_URL}


def test_exhausted_with_no_hits_persists_none_sentinel(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _wire_artists(db, [("a", "Artist A")])

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", lambda mbids, timeout=None: {})
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: None)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single", lambda mbid, timeout=None: None)

    summary = prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    assert summary["none_sentinel"] == 1
    assert db.get_photo_urls(["a"]) == {"a": PHOTO_NONE_SENTINEL}


def test_transient_error_leaves_artist_null_not_sentinel(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _wire_artists(db, [("a", "Artist A")])

    def boom(mbids, timeout=None):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", boom)
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: None)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single", lambda mbid, timeout=None: None)

    summary = prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    # Wikidata errored for "a" -> it must NOT be marked "none" even though
    # Deezer/TheAudioDB cleanly missed; it stays NULL for a later retry.
    assert summary["errors"] == 1
    assert summary["none_sentinel"] == 0
    assert db.get_photo_urls(["a"]) == {"a": None}


def test_rate_limit_aborts_whole_run_and_preserves_prior_hits(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _wire_artists(db, [("a", "Artist A"), ("b", "Artist B")])
    # Force a deterministic processing order (a before b) regardless of how
    # SQLite breaks ties on equal popularity/degree.
    db.set_popularity_bulk([("a", 10), ("b", 5)])

    call_count = {"n": 0}

    def flaky_deezer(name, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return DZ_URL  # "a" resolves fine
        raise _HTTPError429()  # "b" hits the rate limit

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", lambda mbids, timeout=None: {})
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", flaky_deezer)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))

    summary = prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    assert summary["aborted"] == 1
    # "a" already got its URL persisted before the abort.
    assert db.get_photo_urls(["a"])["a"] == DZ_URL
    # "b" never reached the sentinel step -- stays NULL for resume.
    assert db.get_photo_urls(["b"])["b"] is None


def test_resume_skips_already_resolved_artists(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _wire_artists(db, [("a", "Artist A"), ("b", "Artist B")])
    db.set_photo_urls_bulk([("a", WD_URL)])  # "a" already resolved by a prior run

    seen = []

    def tracking_wikidata(mbids, timeout=None):
        seen.extend(mbids)
        return {}

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", tracking_wikidata)
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: DZ_URL)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))

    prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    assert seen == ["b"]  # "a" was excluded from this run entirely
    assert db.get_photo_urls(["a"])["a"] == WD_URL  # untouched


def test_min_degree_filter_skips_tail(tmp_path, monkeypatch):
    db = _db(tmp_path)
    db.add_artist("hub", "Hub")
    db.add_artist("x", "X")
    db.add_artist("tail", "Tail")
    db.add_collaboration("hub", "x", "Song A")
    db.add_collaboration("hub", "tail", "Song B")
    db.refresh_degrees()  # degree is a cached column, not auto-maintained
    # hub: degree 2, x: degree 1, tail: degree 1

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", lambda mbids, timeout=None: {})
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: DZ_URL)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))

    summary = prebake(db, min_degree=2, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0)

    assert summary["candidates"] == 1  # only "hub" qualifies
    assert db.get_photo_urls(["x", "tail"]) == {"x": None, "tail": None}


def test_wikidata_chunking_respects_chunk_size(tmp_path, monkeypatch):
    db = _db(tmp_path)
    ids_names = [(f"a{i}", f"Artist {i}") for i in range(5)]
    _wire_artists(db, ids_names)

    chunk_sizes = []

    def tracking_wikidata(mbids, timeout=None):
        chunk_sizes.append(len(mbids))
        return {}

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", tracking_wikidata)
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: None)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single", lambda mbid, timeout=None: None)

    prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0, wikidata_chunk_size=2)

    assert chunk_sizes == [2, 2, 1]  # 5 artists chunked into groups of 2


def test_seed_ids_restricts_to_exactly_that_set(tmp_path, monkeypatch):
    """A demo (U5) needs its showcase chain's hops force-resolved regardless
    of where they'd fall in the popularity-priority queue."""
    db = _db(tmp_path)
    db.add_artist("popular_hub", "Popular Hub")
    db.add_artist("obscure_tail", "Obscure Tail")
    db.add_collaboration("popular_hub", "obscure_tail", "Song")
    db.set_popularity_bulk([("popular_hub", 100), ("obscure_tail", 1)])

    monkeypatch.setattr(photo_prebake, "resolve_wikidata_batch", lambda mbids, timeout=None: {})
    monkeypatch.setattr(photo_prebake, "resolve_deezer_single", lambda name, timeout=None: DZ_URL)
    monkeypatch.setattr(photo_prebake, "resolve_theaudiodb_single",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))

    summary = prebake(db, wikidata_rate=0, deezer_rate=0, theaudiodb_rate=0,
                       artist_ids=["obscure_tail"])

    assert summary["candidates"] == 1
    assert db.get_photo_urls(["obscure_tail"])["obscure_tail"] == DZ_URL
    assert db.get_photo_urls(["popular_hub"])["popular_hub"] is None  # not in the seed set


def test_resolve_wikidata_batch_validates_and_skips_bad_urls(monkeypatch):
    """Integration point: photo_prebake's stage-1 call goes through
    artist_photo.resolve_wikidata_batch, which must apply the same URL
    validation as the live resolve() path (no un-allowlisted host)."""
    out = artist_photo.resolve_wikidata_batch(
        ["mbid-x"],
        wikidata_fetch=lambda mbids, t: {"mbid-x": "https://evil.example.com/x.jpg"},
    )
    assert out == {}
