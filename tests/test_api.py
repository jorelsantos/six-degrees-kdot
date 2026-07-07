"""
API-layer tests for the FastAPI wrapper (plan 2026-07-06-003, U2).

Verifies engine PARITY (the API serializes resolve_artist / find_connection
output without re-ranking) plus the API-specific contracts: matches_query flag,
disambiguated labels, no-path-vs-404 semantics, graceful preview miss.

A fixture DB is built and pointed at via RABBITHOLE_DB before the app imports,
so these never touch the real 119k-node build or the network.
"""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from database import CollaborationDatabase


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Build a small fixture graph: Kendrick hub + a 1-degree artist + a
    # duplicate-name pair + an orphan (known but unreachable).
    db_path = tmp_path / "api_fixture.db"
    db = CollaborationDatabase(str(db_path))
    db.add_artist("kendrick", "Kendrick Lamar")
    db.add_artist("rihanna", "Rihanna")
    db.add_artist("g1", "The Game")
    db.add_artist("g2", "The Game")
    db.add_artist("orphan", "Lonely Artist")  # exists, no edges
    db.set_popularity("kendrick", 9_000_000)
    db.set_popularity("rihanna", 5_000_000)
    db.set_popularity("g1", 500_000)
    db.set_popularity("g2", 30)
    db.add_collaboration("rihanna", "kendrick", "LOYALTY.",
                         collaborators=["Rihanna", "Kendrick Lamar"])
    db.add_collaboration("g1", "kendrick", "Some Song",
                         collaborators=["The Game", "Kendrick Lamar"])
    db.refresh_degrees()

    # Resolve a Spotify track id on one connecting song (build-time enrichment,
    # U1) so /api/connection can carry it; the other stays NULL (degrades).
    for s in db.get_songs_without_track_id():
        if s["song_name"] == "LOYALTY.":
            db.set_spotify_track_id(s["id"], "loyaltyTrackId")

    monkeypatch.setenv("RABBITHOLE_DB", str(db_path))
    monkeypatch.setenv("RABBITHOLE_KENDRICK_ID", "kendrick")

    # Import fresh so module-level singletons pick up the fixture env.
    sys.modules.pop("main", None)
    api_main = importlib.import_module("main")
    importlib.reload(api_main)
    # Reset the lazy singletons in case another test already initialized them.
    api_main._db = None
    api_main._finder = None
    api_main._kendrick_id = ""
    return TestClient(api_main.app)


def test_health_resolves_kendrick_mbid(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["kendrick_id"] == "kendrick"


def test_search_parity_and_matches_query(client):
    r = client.get("/api/search", params={"q": "Rihanna"})
    body = r.json()
    assert body["candidates"][0]["name"] == "Rihanna"
    assert body["candidates"][0]["matches_query"] is True


def test_search_typo_sets_matches_query_false(client):
    r = client.get("/api/search", params={"q": "rihana"})
    top = r.json()["candidates"][0]
    assert top["name"] == "Rihanna"
    assert top["matches_query"] is False  # notice should fire


def test_search_short_query_is_empty(client):
    assert client.get("/api/search", params={"q": "r"}).json()["candidates"] == []


def test_search_gibberish_empty_200(client):
    r = client.get("/api/search", params={"q": "zxqwvk"})
    assert r.status_code == 200
    assert r.json()["candidates"] == []


def test_search_duplicate_labels_disambiguated(client):
    labels = [c["label"] for c in client.get("/api/search", params={"q": "The Game"}).json()["candidates"]]
    game_labels = [l for l in labels if l.startswith("The Game")]
    assert len(game_labels) == len(set(game_labels))  # distinct
    assert any("collab" in l for l in game_labels)     # qualifier applied


def test_connection_one_degree(client):
    # Resolve Rihanna's id via search, then fetch the connection.
    rid = client.get("/api/search", params={"q": "Rihanna"}).json()["candidates"][0]["id"]
    conn = client.get("/api/connection", params={"artist_id": rid}).json()["connection"]
    assert conn["degrees"] == 1
    assert conn["path"][-1]["name"] == "Kendrick Lamar"


def test_connection_song_details_carry_spotify_track_id(client):
    rid = client.get("/api/search", params={"q": "Rihanna"}).json()["candidates"][0]["id"]
    conn = client.get("/api/connection", params={"artist_id": rid}).json()["connection"]
    details = conn["connections"][0]["song_details"]
    loyalty = next(d for d in details if d["name"] == "LOYALTY.")
    assert loyalty["spotify_track_id"] == "loyaltyTrackId"


def test_connection_song_details_null_track_id_when_unresolved(client):
    gid = client.get("/api/search", params={"q": "The Game"}).json()["candidates"][0]["id"]
    conn = client.get("/api/connection", params={"artist_id": gid}).json()["connection"]
    details = conn["connections"][0]["song_details"]
    assert all(d["spotify_track_id"] is None for d in details)


def test_connection_unknown_artist_404(client):
    assert client.get("/api/connection", params={"artist_id": "nope"}).status_code == 404


def test_connection_known_but_no_path_is_200_null(client):
    r = client.get("/api/connection", params={"artist_id": "orphan"})
    assert r.status_code == 200
    assert r.json()["connection"] is None  # not a 404


def test_connection_kendrick_himself(client):
    r = client.get("/api/connection", params={"artist_id": "kendrick"})
    assert r.json()["connection"]["is_kendrick"] is True


def test_preview_miss_is_null_200(client, monkeypatch):
    # Force a miss without hitting the network.
    import main
    monkeypatch.setattr(main, "get_preview", lambda *a, **k: None)
    r = client.get("/api/preview", params={"song": "zzz", "artists": "nobody"})
    assert r.status_code == 200
    assert r.json()["preview_url"] is None


# --- Lazy resolve-on-Play (plan 007, Path B) ---------------------------------

def test_connection_song_details_carry_song_id(client):
    rid = client.get("/api/search", params={"q": "Rihanna"}).json()["candidates"][0]["id"]
    conn = client.get("/api/connection", params={"artist_id": rid}).json()["connection"]
    sd = conn["connections"][0]["song_details"][0]
    assert isinstance(sd["id"], int) and sd["id"] >= 0  # frontend keys resolve on this


def _unresolved_song_id(client):
    """The 'Some Song' (The Game -> Kendrick) row, which stays NULL in the fixture."""
    gid = client.get("/api/search", params={"q": "The Game"}).json()["candidates"][0]["id"]
    conn = client.get("/api/connection", params={"artist_id": gid}).json()["connection"]
    return conn["connections"][0]["song_details"][0]["id"]


def test_resolve_preview_resolves_and_persists(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "_spotify_token", lambda: "tok")
    calls = {"n": 0}

    def fake_search(query, token, timeout=6.0):
        calls["n"] += 1
        return [{"id": "TRACKXYZ", "name": "Some Song", "artists": [{"name": "The Game"}]}]

    monkeypatch.setattr(main, "search_track", fake_search)
    sid = _unresolved_song_id(client)
    r = client.post("/api/resolve-preview", params={"song_id": sid})
    assert r.status_code == 200
    assert r.json()["spotify_track_id"] == "TRACKXYZ"
    assert calls["n"] == 1
    # Second call reads the persisted id — no new search (R5: resolve once, ever).
    r2 = client.post("/api/resolve-preview", params={"song_id": sid})
    assert r2.json()["spotify_track_id"] == "TRACKXYZ"
    assert calls["n"] == 1


def test_resolve_preview_miss_persists_sentinel(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "_spotify_token", lambda: "tok")
    calls = {"n": 0}

    def fake_search(query, token, timeout=6.0):
        calls["n"] += 1
        return [{"id": "WRONG", "name": "unrelated track", "artists": [{"name": "Nobody"}]}]

    monkeypatch.setattr(main, "search_track", fake_search)
    sid = _unresolved_song_id(client)
    r = client.post("/api/resolve-preview", params={"song_id": sid})
    assert r.json()["spotify_track_id"] is None  # no acceptable match -> sentinel
    # Sentinel persisted -> second call degrades without a new search.
    r2 = client.post("/api/resolve-preview", params={"song_id": sid})
    assert r2.json()["spotify_track_id"] is None
    assert calls["n"] == 1


def test_resolve_preview_no_creds_degrades(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "_spotify_token", lambda: None)  # creds absent
    sid = _unresolved_song_id(client)
    r = client.post("/api/resolve-preview", params={"song_id": sid})
    assert r.status_code == 200
    assert r.json()["spotify_track_id"] is None


def test_resolve_preview_already_resolved_makes_no_call(client, monkeypatch):
    import main

    def boom(*a, **k):
        raise AssertionError("search must not run for an already-resolved song")

    monkeypatch.setattr(main, "_spotify_token", lambda: "tok")
    monkeypatch.setattr(main, "search_track", boom)
    # LOYALTY. is pre-resolved to "loyaltyTrackId" in the fixture.
    rid = client.get("/api/search", params={"q": "Rihanna"}).json()["candidates"][0]["id"]
    conn = client.get("/api/connection", params={"artist_id": rid}).json()["connection"]
    sid = next(d for d in conn["connections"][0]["song_details"] if d["name"] == "LOYALTY.")["id"]
    r = client.post("/api/resolve-preview", params={"song_id": sid})
    assert r.json()["spotify_track_id"] == "loyaltyTrackId"


def test_resolve_preview_unknown_song_404(client):
    assert client.post("/api/resolve-preview", params={"song_id": 999999}).status_code == 404


# --- Edge-preview waterfall (plan 008, U3) -----------------------------------

def _rihanna_id(client):
    return client.get("/api/search", params={"q": "Rihanna"}).json()["candidates"][0]["id"]


def test_edge_preview_returns_first_previewable_song(client, monkeypatch):
    import main
    from preview_resolver import ResolvedPreview
    monkeypatch.setattr(main, "_spotify_token", lambda: None)
    monkeypatch.setattr(
        main, "resolve_waterfall",
        lambda title, artists, spotify_track_id=None, **k: ResolvedPreview(
            source="itunes", audio_url="https://audio.example/x.m4a", matched_title=title),
    )
    r = client.get("/api/edge-preview", params={"a": _rihanna_id(client), "b": "kendrick"})
    body = r.json()
    assert r.status_code == 200
    assert body["song"] == "LOYALTY."
    assert body["source"] == "itunes"
    assert body["audio_url"] == "https://audio.example/x.m4a"
    assert body["fallback_url"] is None


def test_edge_preview_apple_fallback_when_no_preview(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "_spotify_token", lambda: None)
    monkeypatch.setattr(main, "resolve_waterfall", lambda *a, **k: None)
    body = client.get("/api/edge-preview", params={"a": "g1", "b": "kendrick"}).json()
    assert body["source"] is None
    assert body["song"] == "Some Song"
    assert body["fallback_url"] and "music.apple.com" in body["fallback_url"]


def test_edge_preview_persists_none_and_skips_recheck(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "_spotify_token", lambda: None)
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(main, "resolve_waterfall", fake)
    client.get("/api/edge-preview", params={"a": "g1", "b": "kendrick"})  # persists 'none'
    after_first = calls["n"]
    client.get("/api/edge-preview", params={"a": "g1", "b": "kendrick"})  # song now 'none' → skipped
    assert calls["n"] == after_first  # a 'none'-marked song is not re-resolved


def test_edge_preview_nonadjacent_pair_is_empty_200(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "_spotify_token", lambda: None)
    # rihanna & g1 never collaborated → no songs, no crash
    rid = _rihanna_id(client)
    r = client.get("/api/edge-preview", params={"a": rid, "b": "g1"})
    assert r.status_code == 200
    assert r.json()["song"] is None
