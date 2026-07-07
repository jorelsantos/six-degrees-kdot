// Typed client for the FastAPI engine, reached same-origin via the Next rewrite
// (/api/* -> :8000). The frontend never re-ranks or re-derives search policy —
// it renders exactly what these return (R2).

export interface Candidate {
  id: string;
  name: string;
  popularity: number;
  degree: number;
  label: string;
  matches_query: boolean;
}

export interface SearchResponse {
  query: string;
  candidates: Candidate[];
}

export interface ArtistRef {
  id: string;
  name: string;
}

export interface SongDetail {
  id: number; // song row id — passed to resolvePreview so a lazy hit persists
  name: string;
  collaborators: string[];
  // Resolved Spotify track id. null when unresolved (→ lazy resolve-on-Play) or
  // resolved-to-no-match (→ no player). See resolvePreview.
  spotify_track_id: string | null;
}

export interface ConnectionEdge {
  from: ArtistRef;
  to: ArtistRef;
  songs: string[];
  song_details: SongDetail[];
}

export interface Connection {
  degrees: number;
  path: ArtistRef[];
  connections: ConnectionEdge[];
  is_kendrick?: boolean;
}

export async function searchArtists(
  q: string,
  signal?: AbortSignal,
): Promise<Candidate[]> {
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal });
  if (!res.ok) throw new Error(`search failed: ${res.status}`);
  const body: SearchResponse = await res.json();
  return body.candidates;
}

export type ConnectionResult =
  | { status: "ok"; connection: Connection }
  | { status: "no_path" } // known artist, no route to Kendrick
  | { status: "not_found" }; // artist id not in the network (404)

export async function fetchConnection(artistId: string): Promise<ConnectionResult> {
  const res = await fetch(`/api/connection?artist_id=${encodeURIComponent(artistId)}`);
  if (res.status === 404) return { status: "not_found" };
  if (!res.ok) throw new Error(`connection failed: ${res.status}`);
  const body = await res.json();
  if (body.connection == null) return { status: "no_path" };
  return { status: "ok", connection: body.connection as Connection };
}

// Lazy resolve-on-Play (plan 007, Path B). Called when a user plays a song with
// no resolved id: the API does one Spotify search, persists the result, and
// returns the track id (or null if there's no acceptable match). The id is
// cached server-side, so this fires at most once per song, ever.
export async function resolvePreview(songId: number): Promise<string | null> {
  const res = await fetch(`/api/resolve-preview?song_id=${songId}`, { method: "POST" });
  if (!res.ok) return null;
  const body: { spotify_track_id: string | null } = await res.json();
  return body.spotify_track_id;
}

// Edge-preview waterfall (plan 008, U3). For an edge (two artist ids), the API
// returns the first song with a playable preview + a directly-playable audio
// URL (Spotify-scrape / iTunes / Deezer), or an Apple Music search fallback when
// no song has any preview. Resolved at page-load so the UI never shows a dead
// player. `song` is null only when the edge has no songs at all.
export interface EdgePreview {
  song: string | null;
  source: "spotify" | "itunes" | "deezer" | null;
  audio_url: string | null;
  artwork_url: string | null;
  store_url: string | null;
  fallback_url: string | null; // Apple Music search when no preview exists
}

export async function fetchEdgePreview(a: string, b: string): Promise<EdgePreview> {
  const params = new URLSearchParams({ a, b });
  const res = await fetch(`/api/edge-preview?${params.toString()}`);
  if (!res.ok) {
    return { song: null, source: null, audio_url: null, artwork_url: null, store_url: null, fallback_url: null };
  }
  return res.json();
}

export async function fetchPreview(
  song: string,
  artists: string[],
): Promise<{ preview_url: string | null; provider: string | null; store_url: string | null }> {
  const params = new URLSearchParams({ song, artists: artists.join("||") });
  const res = await fetch(`/api/preview?${params.toString()}`);
  if (!res.ok) return { preview_url: null, provider: null, store_url: null };
  return res.json();
}
