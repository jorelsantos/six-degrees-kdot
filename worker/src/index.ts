/**
 * Rabbit Hole Worker API (plan 2026-07-09-001, U7).
 *
 * Thin read layer over the D1 serving DB exported by
 * scripts/export_serving_db.py — every connection is a handful of indexed
 * point lookups over the precomputed path tree (KTD1), never a live graph
 * search. The only runtime upstream call this whole stack makes is the
 * lazy Spotify track-ID resolve in /api/resolve-track (KTD5); everything
 * else is D1 reads.
 */
import { disambiguateLabels, toFts5PrefixQuery, type SearchRow } from "./disambiguate";
import {
  buildQuery,
  getClientToken,
  pickAcceptedTrack,
  searchTrack,
  SpotifyRateLimited,
} from "./spotify";
import { checkResolveTrackRateLimit } from "./ratelimit";

export interface Env {
  DB: D1Database;
  SPOTIFY_CLIENT_ID?: string;
  SPOTIFY_CLIENT_SECRET?: string;
}

const NO_TRACK_SENTINEL = "none";
const SEARCH_MIN_QUERY_LEN = 2;
const DEFAULT_SEARCH_LIMIT = 8;
const MAX_CHAIN_HOPS = 10;

// Cache-Control per KTD7: complete responses (nothing left to lazily
// resolve) are cheap to cache hard; a response containing a retryable NULL
// gets a short TTL so a future resolve-track call isn't frozen out by the
// CDN.
const CACHE_LONG = "public, s-maxage=86400";
const CACHE_SHORT = "public, s-maxage=60";

function json(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
}

interface ArtistRow {
  id: string;
  name: string;
  name_norm: string | null;
  popularity: number;
  degree: number;
  photo_url: string | null;
  kendrick_distance: number | null;
  predecessor_id: string | null;
  via_song_title: string | null;
  via_song_collaborators: string | null;
  via_track_id: string | null;
}

async function getArtist(db: D1Database, id: string): Promise<ArtistRow | null> {
  const row = await db.prepare("SELECT * FROM artists WHERE id = ?").bind(id).first<ArtistRow>();
  return row ?? null;
}

// --- GET /api/search ---------------------------------------------------------

async function handleSearch(url: URL, env: Env): Promise<Response> {
  const q = (url.searchParams.get("q") ?? "").trim();
  const limitParam = Number(url.searchParams.get("limit"));
  const limit = Number.isFinite(limitParam) && limitParam > 0 ? limitParam : DEFAULT_SEARCH_LIMIT;

  if (q.length < SEARCH_MIN_QUERY_LEN) {
    return json({ query: q, candidates: [] });
  }

  const ftsQuery = toFts5PrefixQuery(q);
  let rows: SearchRow[];
  try {
    const result = await env.DB.prepare(
      `SELECT id, name, popularity, degree FROM artists
       WHERE id IN (SELECT DISTINCT artist_id FROM search_fts WHERE search_fts MATCH ?)
       ORDER BY popularity DESC, degree DESC
       LIMIT ?`,
    )
      .bind(ftsQuery, limit)
      .all<SearchRow>();
    rows = result.results ?? [];
  } catch {
    // A malformed MATCH expression (or any D1 hiccup) degrades to "no
    // results" rather than a 500 — search is not a critical failure surface.
    rows = [];
  }

  const labels = disambiguateLabels(rows);
  const qNorm = q.toLowerCase();
  const candidates = rows.map((r, i) => ({
    id: r.id,
    name: r.name,
    popularity: r.popularity,
    degree: r.degree,
    label: labels[i],
    matches_query: r.name.trim().toLowerCase() === qNorm,
  }));

  return json({ query: q, candidates });
}

// --- GET /api/connection ------------------------------------------------------

interface ChainArtistRef {
  id: string;
  name: string;
  photo_url: string | null;
}
interface ChainHop {
  song_name: string | null;
  track_id: string | null;
  artists: string[];
}

async function walkChain(
  db: D1Database,
  startId: string,
): Promise<{ degrees: number; path: ChainArtistRef[]; hops: ChainHop[]; pending: boolean }> {
  const path: ChainArtistRef[] = [];
  const hops: ChainHop[] = [];
  // Tracks the RAW via_track_id values (before display-cleaning collapses
  // sentinel and NULL to the same "no player" rendering) — the cache
  // completeness decision needs to tell "confirmed no match, never changes"
  // (sentinel) apart from "not yet checked, could resolve later" (NULL),
  // which the cleaned display value alone can no longer distinguish.
  let pending = false;

  let current: ArtistRow | null = await getArtist(db, startId);
  for (let i = 0; i < MAX_CHAIN_HOPS; i++) {
    if (!current) throw new Error(`chain walk lost artist mid-path (data integrity issue)`);
    path.push({ id: current.id, name: current.name, photo_url: current.photo_url });
    if (current.predecessor_id === null) break;

    let collaborators: string[] = [];
    try {
      collaborators = current.via_song_collaborators ? JSON.parse(current.via_song_collaborators) : [];
    } catch {
      collaborators = [];
    }
    if (current.via_track_id === null) pending = true;
    hops.push({
      song_name: current.via_song_title,
      track_id: current.via_track_id && current.via_track_id !== NO_TRACK_SENTINEL
        ? current.via_track_id
        : null,
      artists: collaborators,
    });

    current = await getArtist(db, current.predecessor_id);
  }

  return { degrees: path.length - 1, path, hops, pending };
}

async function handleConnection(url: URL, env: Env): Promise<Response> {
  const artistId = url.searchParams.get("artist_id");
  if (!artistId) return json({ error: "artist_id is required" }, { status: 400 });

  const artist = await getArtist(env.DB, artistId);
  if (!artist) return json({ error: "Artist not in network" }, { status: 404 });

  if (artist.kendrick_distance === null) {
    // Known artist, no path (KTD1 accepted risk: could change if the graph's
    // connected components ever split further) — 200, not 404.
    return json({ connection: null }, { headers: { "cache-control": CACHE_SHORT } });
  }

  if (artist.kendrick_distance === 0) {
    return json(
      { connection: { degrees: 0, path: [], hops: [], is_kendrick: true } },
      { headers: { "cache-control": CACHE_LONG } },
    );
  }

  let chain: { degrees: number; path: ChainArtistRef[]; hops: ChainHop[]; pending: boolean };
  try {
    chain = await walkChain(env.DB, artistId);
  } catch {
    return json({ error: "connection lookup failed" }, { status: 500 });
  }

  // "Complete" = nothing left for resolve-track to lazily fill in.
  const cacheControl = chain.pending ? CACHE_SHORT : CACHE_LONG;
  const { degrees, path, hops } = chain;

  return json({ connection: { degrees, path, hops } }, { headers: { "cache-control": cacheControl } });
}

// --- POST /api/resolve-track ---------------------------------------------------

async function handleResolveTrack(url: URL, env: Env, request: Request): Promise<Response> {
  const artistId = url.searchParams.get("artist_id");
  if (!artistId) return json({ error: "artist_id is required" }, { status: 400 });

  const artist = await getArtist(env.DB, artistId);
  if (!artist) return json({ error: "Artist not in network" }, { status: 404 });

  // Already resolved (real id or confirmed sentinel) -> return immediately,
  // no Spotify call, no rate-limit cost. This is what makes repeated calls
  // for the SAME artist free regardless of the limiter below.
  if (artist.via_track_id !== null) {
    const trackId = artist.via_track_id === NO_TRACK_SENTINEL ? null : artist.via_track_id;
    return json({ spotify_track_id: trackId });
  }

  // Only artists with a genuinely unresolved via-song reach here, so the
  // rate limit protects exactly the resource that matters: Spotify quota +
  // D1 write budget spent resolving NEW (not cached) songs.
  const clientIp = request.headers.get("cf-connecting-ip") ?? "unknown";
  if (!checkResolveTrackRateLimit(clientIp)) {
    return json({ error: "rate limited" }, { status: 429 });
  }

  if (!env.SPOTIFY_CLIENT_ID || !env.SPOTIFY_CLIENT_SECRET) {
    return json({ spotify_track_id: null });
  }
  if (!artist.via_song_title) {
    return json({ spotify_track_id: null });
  }

  let collaborators: string[] = [];
  try {
    collaborators = artist.via_song_collaborators ? JSON.parse(artist.via_song_collaborators) : [];
  } catch {
    collaborators = [];
  }

  try {
    const token = await getClientToken(env.SPOTIFY_CLIENT_ID, env.SPOTIFY_CLIENT_SECRET);
    const candidates = await searchTrack(buildQuery(artist.via_song_title, collaborators), token);
    const winner = pickAcceptedTrack(artist.via_song_title, collaborators, candidates);
    const resultValue = winner ? winner.id : NO_TRACK_SENTINEL;

    await env.DB.prepare(
      "UPDATE artists SET via_track_id = ? WHERE id = ? AND via_track_id IS NULL",
    )
      .bind(resultValue, artistId)
      .run();

    return json({ spotify_track_id: winner ? winner.id : null });
  } catch (err) {
    if (err instanceof SpotifyRateLimited) {
      return json({ error: "spotify rate limited" }, { status: 429 });
    }
    // Transient failure: leave via_track_id NULL for a later retry, don't 500
    // the whole request over a Spotify hiccup.
    return json({ spotify_track_id: null }, { headers: { "cache-control": CACHE_SHORT } });
  }
}

// --- Router --------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/api/search" && request.method === "GET") {
      return handleSearch(url, env);
    }
    if (url.pathname === "/api/connection" && request.method === "GET") {
      return handleConnection(url, env);
    }
    if (url.pathname === "/api/resolve-track" && request.method === "POST") {
      return handleResolveTrack(url, env, request);
    }

    return json({ error: "not found" }, { status: 404 });
  },
};
