# Spotify preview spike — go/no-go (2026-07-06)

**Unit:** U4 of the 2026-07-06 search/preview refinement plan.
**Question:** Can we get a usable Spotify 30s preview cleanly enough to adopt over iTunes/Deezer?
**Verdict: NO-GO.** Keep iTunes → Deezer as the audio-preview path (unchanged).

## What the spike tested (safety-bounded: 6/20 requests, no 429, app token only)

Client-credentials token flow + `/v1/search` for 4 hand-picked tracks + an oEmbed check.
Script: `scripts/spike_spotify_preview.py` (experimental; safe by construction — hard ≤20-request
budget, aborts on 429, no graph iteration, no personal-account login).

## Findings

| Signal | Result |
|---|---|
| Client-credentials token | ✅ acquired (single app-level token, no user OAuth) |
| track_id via `/v1/search` | ✅ 4/4 |
| **`preview_url` via `/v1/search`** | ❌ **0/4 — null for every track** |
| oEmbed embed player | ✅ available |

The key result: the `/v1/search` `preview_url` "workaround" that circulated in 2024 is **now
also dead** (as of July 2026). Spotify has removed the 30s preview MP3 from client-credentials
API responses entirely — not just from the track GET. There is no API route to a raw Spotify
preview audio URL anymore.

## Why NO-GO (against the plan's KTD4 decision gate)

Adoption required ALL of: single client-cred token ✅, reliable, UX not worse than iTunes/Deezer,
AND a zero-runtime-call (build-time-resolved) path. It fails on the two that matter:

1. **No audio to adopt.** The only surviving Spotify route is the **embed iframe** — a full
   Spotify player (un-styleable), not a 30s clip we can play in the current custom `<audio>`
   element with a clean "Listen on…" link-out. That is a UX *downgrade* from today's path, not a win.
2. **Goal mismatch.** The feature is a lightweight inline 30s preview. The embed player is a
   different, heavier interaction and belongs to the Track 2 design pass *if* desired as an
   additional "open in Spotify" affordance — never as a replacement for the audio preview.

Rate-limit/ban risk was never the deciding factor (the spike was trivially safe); the route simply
doesn't deliver the thing we wanted. This matches the anticipated outcome ("if it's the same API
mess, default to iTunes").

## Decision

- **No production changes.** `src/preview_fetcher.py` and `app.py` are untouched — iTunes → Deezer
  stays the audio preview path.
- If a "Listen on Spotify" link/embed is ever wanted, resolve `track_id` once at **build time**
  (bounded, like the popularity enrichment) so runtime makes zero app-keyed Spotify calls, and
  treat it as a design-pass affordance. Deferred, not scheduled.
