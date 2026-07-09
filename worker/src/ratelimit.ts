/**
 * Rate limit for POST /api/resolve-track (doc review finding, P1 — security
 * lens): the one endpoint that spends real external resources (Spotify
 * quota + a D1 write) on every genuinely-new resolution. Without a limit, a
 * script iterating over many different unresolved artists could burn the
 * Spotify app's quota, degrading track resolution for real visitors on a
 * platform with no other cost signal to notice by.
 *
 * This is an in-memory sliding window scoped to ONE Worker isolate — it
 * resets on isolate recycle and does not coordinate across isolates. That is
 * a deliberate v1 tradeoff: it requires no extra Cloudflare account setup
 * (no KV/Durable Object binding to provision) and stops the common case
 * (one script hammering the endpoint within a session) outright. If real
 * abuse ever shows up, the documented upgrade path is a Cloudflare native
 * Rate Limiting rule on this route (dashboard-configured, no code change).
 */
const WINDOW_MS = 60_000;
const MAX_PER_WINDOW = 20; // global cap across all callers, not per-IP — the
// resource being protected (Spotify quota) is shared, so a global budget is
// the correct unit, not per-visitor fairness.

let windowStart = 0;
let windowCount = 0;

export function checkResolveTrackRateLimit(_clientIp: string): boolean {
  const now = Date.now();
  if (now - windowStart > WINDOW_MS) {
    windowStart = now;
    windowCount = 0;
  }
  windowCount += 1;
  return windowCount <= MAX_PER_WINDOW;
}

/** Test-only: reset module state between test cases. */
export function _resetForTests(): void {
  windowStart = 0;
  windowCount = 0;
}
