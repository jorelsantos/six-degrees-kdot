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
    db.add_collaboration("rihanna", "kendrick", "LOYALTY.")
    db.add_collaboration("g1", "kendrick", "Some Song")
    db.refresh_degrees()

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
