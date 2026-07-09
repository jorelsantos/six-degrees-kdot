"""
FastAPI wrapper over the Rabbit Hole engine (plan 2026-07-06-003, U2).

LOCAL DEV / VALIDATION TOOL ONLY as of plan 2026-07-09-001 (U9) — the public
app is served by the Cloudflare Worker (worker/src/index.ts) over the
precomputed path tree in D1, not this API. This module still matters for two
things: (1) local frontend/engine development against the live MusicBrainz
graph, and (2) the BFS oracle that src/path_tree.py's precompute validates
itself against (`PathFinder` here is ground truth). Nothing here is deleted —
it stays exactly as capable as it always was, just no longer what production
traffic hits.

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
  ...`), so we insert src/ on sys.path (below) rather than importing src as a
  package.
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

# --- Import the engine via src/ on sys.path (flat imports in src/) ------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from database import (  # noqa: E402
    CollaborationDatabase, disambiguate_labels, NO_TRACK_SENTINEL, PHOTO_NONE_SENTINEL,
)
from path_finder_sqlite import PathFinder  # noqa: E402
from preview_fetcher import get_preview  # noqa: E402
import artist_photo  # noqa: E402
from spotify_enrich import (  # noqa: E402
    get_client_token, search_track, _build_query, _resolve_track_id, RateLimited,
)
# Aliased: the /api/resolve-preview endpoint function below is also named
# resolve_preview and would shadow this import (name collision).
from preview_resolver import resolve_preview as resolve_waterfall, apple_search_url  # noqa: E402
import album_color  # noqa: E402


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

# --- DB path resolution: MusicBrainz build if present, else legacy Spotify ----
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


class EdgePreviewResponse(BaseModel):
    # The first previewable song on an edge + its playable preview (plan 008).
    # song is None only when the edge has no songs at all. When no song has any
    # preview, source/audio_url are None and fallback_url is the Apple search.
    song: Optional[str]
    source: Optional[str]          # 'spotify' | 'itunes' | 'deezer' | None
    audio_url: Optional[str]       # directly-playable mp3/m4a (re-resolved fresh)
    artwork_url: Optional[str]
    store_url: Optional[str]
    fallback_url: Optional[str]    # Apple Music search link when no preview exists
    artists: List[str] = []        # credited lineup (from the MusicBrainz edge)
    album: Optional[str] = None
    year: Optional[int] = None
    dominant_color: Optional[str] = None  # '#rrggbb' from the cover, for card theming


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
    a known artist with no path returns 200 {"connection": null} (the no-path
    case matters once the bootleg-edge filter can disconnect components).

    Each path artist is enriched with a `photo_url` (plan 010): unchecked
    artists are resolved via the coverage waterfall, the result is persisted
    (URL, or the "none" sentinel when every source missed; a transient failure
    leaves the row NULL to retry later), and each node carries a normalized
    `photo_url` (a real URL or null) for the chain avatar."""
    db = _get_db()
    if db.get_artist(artist_id) is None:
        raise HTTPException(status_code=404, detail="Artist not in network")
    if artist_id == _kendrick_id:
        return ConnectionResponse(connection={"degrees": 0, "path": [], "connections": [], "is_kendrick": True})
    conn = _finder.find_connection(artist_id, _kendrick_id)
    if conn is not None:
        _attach_photo_urls(db, conn.get("path", []))
    return ConnectionResponse(connection=conn)  # conn is None => no path, still 200


def _attach_photo_urls(db: CollaborationDatabase, path: List[dict]) -> None:
    """Enrich each path node ({id, name}) in place with a normalized `photo_url`
    (a validated image URL or None). Reads the persisted cache, resolves only
    unchecked artists through the waterfall (bounded by artist_photo's per-call
    budget), and persists the outcome so each artist is resolved at most once.

    Never raises — a resolver failure degrades to null photos (the chain shows
    the initials/silhouette fallback), never a 500 on the core endpoint."""
    if not path:
        return
    ids = [node["id"] for node in path]
    cached = db.get_photo_urls(ids)  # {id: url | "none" | None}

    unchecked = [
        (node["id"], node.get("name", ""))
        for node in path
        if cached.get(node["id"]) is None
    ]
    resolved: dict = {}
    if unchecked:
        try:
            resolved = artist_photo.resolve(unchecked)
        except Exception:  # defensive: the resolver already swallows source errors
            resolved = {}
        persist: List[tuple] = []
        for mbid, result in resolved.items():
            if result == artist_photo.UNAVAILABLE:
                continue  # leave NULL — retry on a later request
            value = PHOTO_NONE_SENTINEL if result == artist_photo.NO_PHOTO else result
            persist.append((mbid, value))
        if persist:
            db.set_photo_urls_bulk(persist)

    for node in path:
        raw = cached.get(node["id"])
        if raw is None:  # was unchecked — use what we just resolved
            raw = resolved.get(node["id"])
        # Normalize to a real URL or null: the "none" sentinel and the
        # NO_PHOTO/UNAVAILABLE tri-state markers all render as no photo.
        if isinstance(raw, str) and raw not in (
            PHOTO_NONE_SENTINEL, artist_photo.NO_PHOTO, artist_photo.UNAVAILABLE
        ):
            node["photo_url"] = raw
        else:
            node["photo_url"] = None


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


@app.get("/api/edge-preview", response_model=EdgePreviewResponse)
def edge_preview(a: str, b: str) -> EdgePreviewResponse:
    """Plan 008, U3 — the first song on an edge (a,b) that has a playable preview,
    resolved at page-load so the UI only ever shows previewable songs (R1: no
    dead buttons). Walks the edge's ordered songs; for each unchecked one, lazily
    resolves a Spotify track id (once) then runs the preview waterfall
    (spotify-scrape → iTunes → Deezer), persisting the winning source (or 'none').
    Returns the first hit; if no song has any preview, returns the Apple Music
    search fallback (R5). The audio URL is re-resolved fresh each call (URLs
    expire — we persist source/identity, not the volatile URL: KTD3).

    Demo-scoped: makes upstream calls; needs public guardrails before deploy."""
    db = _get_db()
    songs = db.get_collaboration_song_details(a, b)
    if not songs:
        return EdgePreviewResponse(song=None, source=None, audio_url=None,
                                   artwork_url=None, store_url=None, fallback_url=None)

    token: Optional[str] = None
    token_tried = False
    for s in songs:
        if s.get("preview_source") == "none":
            continue  # already checked — no preview anywhere
        tid = s["spotify_track_id"]  # real id or None (sentinel normalized)
        unchecked = s.get("preview_source") is None

        if unchecked and tid is None:
            # Lazily resolve a Spotify track id once (reuses the plan-007 seam).
            if not token_tried:
                token, token_tried = _spotify_token(), True
            if token:
                try:
                    cands = search_track(_build_query(s["name"], s["collaborators"]), token)
                    resolved = _resolve_track_id(s["name"], s["collaborators"], cands)
                except (RateLimited, requests.RequestException, ValueError):
                    resolved = None
                if resolved:
                    db.set_spotify_track_id(s["id"], resolved)
                    tid = None if resolved == NO_TRACK_SENTINEL else resolved

        pv = resolve_waterfall(s["name"], s["collaborators"], spotify_track_id=tid)
        if unchecked:
            db.set_preview_source(s["id"], pv.source if pv else "none")
        if pv:
            return EdgePreviewResponse(
                song=s["name"], source=pv.source, audio_url=pv.audio_url,
                artwork_url=pv.artwork_url, store_url=pv.store_url, fallback_url=None,
                artists=s["collaborators"], album=pv.album, year=pv.year,
                dominant_color=album_color.dominant_color(pv.artwork_url),
            )

    # No previewable song on this edge → Apple Music search fallback (R5).
    top = songs[0]
    artist = top["collaborators"][0] if top["collaborators"] else ""
    return EdgePreviewResponse(
        song=top["name"], source=None, audio_url=None, artwork_url=None,
        store_url=None, fallback_url=apple_search_url(top["name"], artist),
        artists=top["collaborators"],
    )
