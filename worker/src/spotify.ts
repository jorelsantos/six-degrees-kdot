/**
 * Official Spotify Web API client for the Worker's lazy track-ID resolve
 * (plan 2026-07-09-001, U7/KTD5). Client-credentials only — no user auth,
 * no scraping. Match-guard ported verbatim from src/preview_fetcher.py's
 * _accept/_title_matches/_artist_matches so the Worker's lazy resolve and
 * the offline pre-bake (src/track_prebake.py) apply IDENTICAL acceptance
 * logic — a song that would have gotten a sentinel offline must also get a
 * sentinel here, and vice versa.
 */
const TOKEN_URL = "https://accounts.spotify.com/api/token";
const SEARCH_URL = "https://api.spotify.com/v1/search";
const SEARCH_LIMIT = 5;

// Module-scope cache: survives across requests within one warm isolate, not
// guaranteed across isolate recycles — acceptable for a ~50-minute token.
let cachedToken: { token: string; expiresAt: number } | null = null;

export async function getClientToken(clientId: string, clientSecret: string): Promise<string> {
  const now = Date.now();
  if (cachedToken && cachedToken.expiresAt > now) return cachedToken.token;

  const auth = btoa(`${clientId}:${clientSecret}`);
  const resp = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${auth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials",
  });
  if (!resp.ok) throw new Error(`spotify token request failed: ${resp.status}`);
  const data = (await resp.json()) as { access_token: string; expires_in: number };
  cachedToken = { token: data.access_token, expiresAt: now + (data.expires_in - 60) * 1000 };
  return data.access_token;
}

export interface SpotifyTrack {
  id: string;
  name: string;
  artists: { name: string }[];
}

export async function searchTrack(query: string, token: string): Promise<SpotifyTrack[]> {
  const url = new URL(SEARCH_URL);
  url.searchParams.set("q", query);
  url.searchParams.set("type", "track");
  url.searchParams.set("limit", String(SEARCH_LIMIT));

  const resp = await fetch(url.toString(), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (resp.status === 429) {
    const retryAfter = resp.headers.get("Retry-After");
    throw new SpotifyRateLimited(retryAfter ? Number(retryAfter) : undefined);
  }
  if (!resp.ok) throw new Error(`spotify search failed: ${resp.status}`);
  const data = (await resp.json()) as { tracks?: { items?: SpotifyTrack[] } };
  return data.tracks?.items ?? [];
}

export class SpotifyRateLimited extends Error {
  retryAfter?: number;
  constructor(retryAfter?: number) {
    super("Spotify rate limit (429)");
    this.retryAfter = retryAfter;
  }
}

function normalize(text: string): string {
  let t = text.toLowerCase();
  t = t.replace(/[([][^)\]]*[)\]]/g, " "); // drop parentheticals/brackets
  t = t.replace(/\b(feat|ft|featuring|with)\b.*/, " "); // drop "feat." clauses
  t = t.replace(/[^a-z0-9 ]/g, " ");
  return t.split(/\s+/).filter(Boolean).join(" ");
}

function titleMatches(querySong: string, candidateTitle: string): boolean {
  const q = normalize(querySong);
  const c = normalize(candidateTitle);
  if (!q || !c) return false;
  if (q === c) return true;
  return c.includes(q) || q.includes(c);
}

function artistMatches(artistNames: string[], candidateArtist: string): boolean {
  const cand = normalize(candidateArtist);
  if (!cand) return false;
  for (const a of artistNames) {
    const na = normalize(a);
    if (na.length >= 3 && (cand.includes(na) || na.includes(cand))) return true;
  }
  return false;
}

export function buildQuery(songName: string, artistNames: string[]): string {
  const artists = artistNames.filter(Boolean).join(" ");
  return `${songName} ${artists}`.trim();
}

/** Same contract as src/spotify_enrich.py's _resolve_track_id: the first
 * candidate whose title AND artist both pass the guard wins; otherwise the
 * caller persists the "none" sentinel (a wrong id is worse than none). */
export function pickAcceptedTrack(
  songName: string,
  artistNames: string[],
  candidates: SpotifyTrack[],
): SpotifyTrack | null {
  for (const track of candidates) {
    const artistField = track.artists.map((a) => a.name).join(", ");
    if (titleMatches(songName, track.name) && artistMatches(artistNames, artistField)) {
      return track;
    }
  }
  return null;
}
