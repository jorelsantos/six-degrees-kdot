"""
FastAPI wrapper over the Rabbit Hole engine (plan 2026-07-06-003, U2).

The Python layer stays the single source of truth for ranking, resolution,
pathfinding, and preview fetching. This wrapper serializes engine output
verbatim — it never re-ranks or re-implements search policy (R2). The Next.js
frontend is a dumb renderer of what these endpoints return.

Design notes:
- Plain `def` endpoints (NOT async): the engine is synchronous (sqlite +
  requests-based get_preview with 6s-per-provider timeouts). FastAPI runs sync
  endpoints in a threadpool; an async endpoint calling get_preview would block
  the event loop and stall the typeahead. src/database.py opens a fresh SQLite
  connection per call, so the threadpool is safe.
- src/ modules use flat imports (path_finder_sqlite does `from database import
  ...`), so we replicate app.py's sys.path insert rather than importing src as
  a package.
- Kendrick's node id is resolved from the active DB (MBID for the MusicBrainz
  build), never PathFinder's hardcoded legacy Spotify default — that default
  returns no-path for the entire MB graph.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Import the engine the same way app.py does (flat imports in src/) --------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from database import CollaborationDatabase, disambiguate_labels, NO_TRACK_SENTINEL  # noqa: E402
from path_finder_sqlite import PathFinder  # noqa: E402
from preview_fetcher import get_preview  # noqa: E402
from spotify_enrich import (  # noqa: E402
    get_client_token, search_track, _build_query, _resolve_track_id, RateLimited,
)


def _load_dotenv() -> None:
    """Load SPOTIFY_* creds from the repo .env into the process env if present
    and not already set, so `uvicorn api.main:app` picks them up without extra
    setup. Placeholder values ("...here") are ignored. No new dependency."""
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if key and val and "here" not in val and not os.environ.get(key):
            os.environ[key] = val


_load_dotenv()

# Cached client-credentials token (KTD5 — fetch once, reuse; do NOT re-auth per
# request). Client-credentials tokens live ~3600s; refresh a little early.
_token_cache: dict = {"token": None, "exp": 0.0}


def _spotify_token() -> Optional[str]:
    """Return a cached Spotify client-credentials token, or None if creds are
    absent / auth fails (the caller then degrades to no player)."""
    cid = os.environ.get("SPOTIFY_CLIENT_ID")
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        return None
    now = time.monotonic()
    if _token_cache["token"] and now < _token_cache["exp"]:
        return _token_cache["token"]
    try:
        token = get_client_token(cid, secret)
    except (requests.RequestException, ValueError, KeyError):
        return None
    _token_cache["token"] = token
    _token_cache["exp"] = now + 3000.0  # ~50 min; tokens last ~60
    return token

# --- DB path resolution mirrors app.py's resolve_db_path ----------------------
_DATA_DIR = _ROOT / "data"
MB_DB_PATH = _DATA_DIR / "collaboration_network_mb.db"
SPOTIFY_DB_PATH = _DATA_DIR / "collaboration_network.db"


def resolve_db_path() -> Path:
    env = os.environ.get("RABBITHOLE_DB")
    if env:
        return Path(env)
    if MB_DB_PATH.exists():
        return MB_DB_PATH
    return SPOTIFY_DB_PATH


# --- App + lazily-initialized singletons --------------------------------------
app = FastAPI(title="Rabbit Hole API", version="1.0.0")

# CORS is a belt-and-suspenders fallback; in normal operation the Next.js
# rewrite proxies /api/* same-origin so the browser never makes a cross-origin
# request. Kept permissive for localhost dev only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_db: Optional[CollaborationDatabase] = None
_finder: Optional[PathFinder] = None
_kendrick_id: str = ""


def _get_db() -> CollaborationDatabase:
    """Lazily open the DB. Guards existence first — CollaborationDatabase's
    constructor would otherwise CREATE an empty DB and we'd silently serve an
    empty network."""
    global _db, _finder, _kendrick_id
    if _db is None:
        db_path = resolve_db_path()
        if not db_path.exists():
            raise HTTPException(
                status_code=503,
                detail=f"Collaboration DB not found at {db_path}. Build it first.",
            )
        _db = CollaborationDatabase(str(db_path))
        _finder = PathFinder(_db)
        env = os.environ.get("RABBITHOLE_KENDRICK_ID")
        if env:
            _kendrick_id = env
        else:
            artist = _db.get_artist_by_name("Kendrick Lamar")
            _kendrick_id = artist["id"] if artist else ""
    return _db


# --- Response models ----------------------------------------------------------
class Candidate(BaseModel):
    id: str
    name: str
    popularity: int
    degree: int
    label: str          # disambiguated display label (U4/R6)
    matches_query: bool  # False => "Showing results for X" notice fires (R2)


class SearchResponse(BaseModel):
    query: str
    candidates: List[Candidate]


class ConnectionResponse(BaseModel):
    # The path payload (degrees, path[], connections[] with from/to/songs/
    # song_details) is passed through verbatim from find_connection — the "from"
    # key isn't a legal Python field name, so we serialize it as an opaque dict
    # rather than a model to preserve the engine shape exactly. None => known
    # artist with no path (200, not 404).
    connection: Optional[dict]


class PreviewResponse(BaseModel):
    preview_url: Optional[str]
    provider: Optional[str]
    store_url: Optional[str]


class ResolvePreviewResponse(BaseModel):
    # The resolved Spotify track id (embeddable), or None when the song has no
    # acceptable match / creds are absent — the row then degrades to no player.
    spotify_track_id: Optional[str]


# --- Endpoints ----------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    db = _get_db()
    return {"status": "ok", "kendrick_id": _kendrick_id, "db": str(resolve_db_path())}


@app.get("/api/search", response_model=SearchResponse)
def search(q: str, limit: int = 8) -> SearchResponse:
    """Ranked candidates from resolve_artist, serialized verbatim (no re-rank).
    Adds a disambiguated `label` and a server-computed `matches_query` flag so
    the frontend never does a client-side string comparison (Unicode-divergent)."""
    db = _get_db()
    q = q.strip()
    if len(q) < 2:
        return SearchResponse(query=q, candidates=[])
    rows = db.resolve_artist(q, limit=limit)
    labels = disambiguate_labels(rows)
    q_norm = q.lower()
    candidates = [
        Candidate(
            id=r["id"],
            name=r["name"],
            popularity=r["popularity"],
            degree=r.get("degree", 0),
            label=label,
            matches_query=(r["name"].strip().lower() == q_norm),
        )
        for r, label in zip(rows, labels)
    ]
    return SearchResponse(query=q, candidates=candidates)


@app.get("/api/connection", response_model=ConnectionResponse)
def connection(artist_id: str) -> ConnectionResponse:
    """Path from an artist to Kendrick. 404 only when the artist id is unknown;
    a known artist with no path returns 200 {"connection": null} (parity with
    app.py — matters once the bootleg-edge filter can disconnect components)."""
    db = _get_db()
    if db.get_artist(artist_id) is None:
        raise HTTPException(status_code=404, detail="Artist not in network")
    if artist_id == _kendrick_id:
        return ConnectionResponse(connection={"degrees": 0, "path": [], "connections": [], "is_kendrick": True})
    conn = _finder.find_connection(artist_id, _kendrick_id)
    return ConnectionResponse(connection=conn)  # conn is None => no path, still 200


@app.get("/api/preview", response_model=PreviewResponse)
def preview(song: str, artists: str = "") -> PreviewResponse:
    """30s preview via get_preview (iTunes -> Deezer). Never raises; a miss is a
    null body with 200 so the row degrades gracefully to no player."""
    artist_list = [a for a in artists.split("||") if a]
    result = get_preview(song, artist_list)
    if result is None:
        return PreviewResponse(preview_url=None, provider=None, store_url=None)
    return PreviewResponse(
        preview_url=result.preview_url,
        provider=result.provider,
        store_url=result.store_url,
    )


@app.post("/api/resolve-preview", response_model=ResolvePreviewResponse)
def resolve_preview(song_id: int) -> ResolvePreviewResponse:
    """Lazy resolve-on-Play (plan 007, Path B — the preview workhorse). Resolves
    ONE song's Spotify track id via a single search, persists it, and returns it.
    Called only when a user plays a song with no resolved id, so the batch crawl
    is avoided (the offline pipeline wasn't worth building: plan 007 found the
    lazy path resolves ~78% of displayed songs vs ~15% for the best offline
    source). Each song resolves at most once, ever — a second view reads the
    cached id and makes no call.

    Reads the title + credited lineup from the DB (never trusts client input for
    the query). Degrades to spotify_track_id=None on any miss / creds-absent /
    network error, leaving the row NULL for a later retry rather than crashing.

    NOTE: this endpoint makes a live Spotify call and MUST NOT be exposed to
    public traffic without guardrails (global rate limit, per-IP limit, daily
    budget) — deferred to the deployment plan (see frontend/DESIGN-NOTES.md)."""
    db = _get_db()
    song = db.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")

    existing = song["spotify_track_id"]
    # Already resolved (real id) or already searched (sentinel) — no new call.
    if existing == NO_TRACK_SENTINEL:
        return ResolvePreviewResponse(spotify_track_id=None)
    if existing:
        return ResolvePreviewResponse(spotify_track_id=existing)

    token = _spotify_token()
    if token is None:
        return ResolvePreviewResponse(spotify_track_id=None)  # no creds → degrade

    artists = song["collaborators"]
    try:
        candidates = search_track(_build_query(song["name"], artists), token)
        track_id = _resolve_track_id(song["name"], artists, candidates)
    except (RateLimited, requests.RequestException, ValueError):
        # Leave NULL for a later retry; degrade this render to no player.
        return ResolvePreviewResponse(spotify_track_id=None)

    db.set_spotify_track_id(song_id, track_id)
    return ResolvePreviewResponse(
        spotify_track_id=None if track_id == NO_TRACK_SENTINEL else track_id,
    )
