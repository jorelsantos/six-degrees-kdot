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
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Import the engine the same way app.py does (flat imports in src/) --------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from database import CollaborationDatabase, disambiguate_labels  # noqa: E402
from path_finder_sqlite import PathFinder  # noqa: E402
from preview_fetcher import get_preview  # noqa: E402

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
    allow_methods=["GET"],
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
