// Typed client for the Worker API, reached same-origin via the Next rewrite
// (/api/* -> the Cloudflare Worker, plan 2026-07-09-001, U8). The frontend
// never re-ranks or re-derives search policy — it renders exactly what these
// return (R2).

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

// R7: distinguishes "the backend told us something" from "the request
// itself failed" so the UI never shows the same message for both.
export type SearchResult =
  | { status: "ok"; candidates: Candidate[] }
  | { status: "error" };

export async function searchArtists(q: string, signal?: AbortSignal): Promise<SearchResult> {
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal });
    if (!res.ok) return { status: "error" };
    const body: SearchResponse = await res.json();
    return { status: "ok", candidates: body.candidates };
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err; // superseded request, not a failure
    return { status: "error" };
  }
}

export interface ArtistRef {
  id: string;
  name: string;
  // Resolved artist photo (plan 010). A validated image URL, or null when no
  // source had one — the chain then shows the initials fallback.
  photo_url: string | null;
}

export interface HopDetail {
  song_name: string | null;
  // Resolved Spotify track id. null when unresolved (→ lazy resolve-on-Play
  // via resolveTrack) or resolved-to-no-match (→ no player).
  track_id: string | null;
  artists: string[]; // credited lineup, for the no-player card and embed alt text
}

export interface Connection {
  degrees: number;
  path: ArtistRef[];
  hops: HopDetail[]; // one fewer than path.length; hops[i] connects path[i] to path[i+1]
  is_kendrick?: boolean;
}

export type ConnectionResult =
  | { status: "ok"; connection: Connection }
  | { status: "no_path" } // known artist, no route to Kendrick
  | { status: "not_found" } // artist id not in the network (404)
  | { status: "error" }; // R7: backend failure, timeout, or network error — NOT the same as not_found

export async function fetchConnection(artistId: string): Promise<ConnectionResult> {
  try {
    const res = await fetch(`/api/connection?artist_id=${encodeURIComponent(artistId)}`);
    if (res.status === 404) return { status: "not_found" };
    if (!res.ok) return { status: "error" };
    const body = await res.json();
    if (body.connection == null) return { status: "no_path" };
    return { status: "ok", connection: body.connection as Connection };
  } catch {
    return { status: "error" }; // network failure — never collapses to not_found
  }
}

// Lazy resolve-on-Play (KTD5). Called when a hop's via-song has no resolved
// track id: the Worker does one official Spotify search, persists the
// result, and returns the id (or null if there's no acceptable match / the
// endpoint is rate-limited). Fires at most once per song per visitor session
// — SpotifyEmbed only calls this for a hop whose track_id is null.
export async function resolveTrack(artistId: string): Promise<string | null> {
  try {
    const res = await fetch(`/api/resolve-track?artist_id=${encodeURIComponent(artistId)}`, {
      method: "POST",
    });
    if (!res.ok) return null;
    const body: { spotify_track_id: string | null } = await res.json();
    return body.spotify_track_id;
  } catch {
    return null;
  }
}
