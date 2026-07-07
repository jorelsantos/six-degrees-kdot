# Rabbit Hole — Design Notes

A **concept** design system inspired by Spotify's public visual language, built for
a portfolio piece framed as "a feature I'd love to see in Spotify." This document
is the design system's source of truth and its legal-safety record.

## Provenance of the tokens (`design/tokens.json`)

**Observation-derived (clean-room).** The planned automated extractor
(`design-extract`) resolved on npm to an unrelated tool (screen-recording
extraction), so per the plan's KTD3 we used the guaranteed observation floor:
the palette, radii, and pill-button language already validated in the retired
Streamlit app (`app.py`), extended by observation of Spotify's public web UI
into a full scale (type, spacing rhythm, elevation, motion). No bytes were
taken from Spotify's stylesheets, scripts, images, or font files — every value
was re-typed from observation. This is the more defensible path anyway: an
original implementation of an observed style, not a copy of protected files.

## Legal-safety checklist (KTD5)

- [x] **Tokens by observation, not extraction of asset/code files** — values re-typed, not lifted.
- [x] **Original components** — all CSS/JSX authored here; no Spotify markup or classes.
- [x] **Look-alike open font** — Figtree (OFL, designed as a free Circular-alike), committed locally under `frontend/fonts/`. Never Circular or Spotify Mix (both proprietary; Spotify moved to custom "Spotify Mix" in 2024).
- [x] **No Spotify logo / wordmark** used as branding anywhere.
- [x] **No Spotify assets, images, or code** from their bundle.
- [x] **Non-affiliation disclaimer** rendered in the app footer: "An unofficial concept — not affiliated with Spotify."
- [x] **"Concept" framing** in the app and README (nominative use: we may name Spotify to describe what the concept is *for*).
- [x] **Data attribution preserved** — MusicBrainz (CC0) + the official Spotify embed player (see below). iTunes/Deezer attribution retired with the previews (plan 004, R3).
- [x] **Spotify embed = sanctioned use (plan 004, R7)** — the previews render via Spotify's own `open.spotify.com/embed/track/{id}` iframe, Spotify's official, publicly-documented sharing mechanism (it serves its own player, controls, and branding inside the frame). We embed by track id only; we do not proxy, download, or re-host any audio, and we make **zero** Spotify API calls at runtime — track ids are resolved once at build time (`src/spotify_enrich.py`) and persisted. `allow="encrypted-media"` is a required, tested attribute (omitting it silently disables playback).
- [x] **Spotify-app chrome is clean-room + inert (plan 004, R4/KTD3)** — `app-chrome.tsx` recreates the *shape* of a music-app shell (sidebar, top bar, avatar) from observation using our own tokens. Look-and-feel (layout, dark surfaces, nav shape) is not protected; the from-scratch lookalike is the established concept-portfolio path and is **less** fraught than pasting Spotify's actual screenshot as a backdrop (explicitly rejected). Hard lines held: **no Spotify logo/wordmark**, no lifted icons (all nav icons are original inline SVGs), no lifted assets/code. The chrome is non-interactive (nav is `aria-hidden`, `cursor-default`, routes nowhere); Rabbit Hole is the single live surface. **This checklist is the guard against a future contributor adding the real logo "for realism."**

## Token summary

- **Brand green** `#1DB954` (classic) / `#1ED760` (bright accent, focus ring).
- **Dark surfaces** `#121212` base → `#181818` raised → `#282828` overlay, with hover steps.
- **Type** Figtree; tight display sizes with `-0.02em` tracking, 8px-grid spacing, 4/8/12/500px radii.
- Full values in `design/tokens.json`; wired into Tailwind theme + CSS vars in U3.

## Parity checklist (U6) — Streamlit behaviors preserved in the Next.js UI

Enumerated from `app.py` and verified in the live preview (desktop + 375px mobile):

- [x] **Ranked typeahead suggestions** — dumb-renders API order; Rihanna leads "rihana". (Streamlit: 2-col buttons; new: real debounced dropdown with keyboard nav.)
- [x] **Auto-run top match on submit** with server-driven "Showing results for X" notice — verified "beyonce" → Beyoncé.
- [x] **Disambiguated duplicate labels** — "The Game · 573 collabs" etc., no double-count.
- [x] **Degree header** — compact, no emoji, "N Degree(s) of separation".
- [x] **Artist cards** with green accent underline for every hop.
- [x] **"Collaborated On" pair label** — "Frank Sinatra × Count Basie" per edge; 3-degree chain verified.
- [x] **Per-song "with X, Y"** collaborator line (endpoints excluded).
- [x] **30s preview via the Spotify embed player (plan 004)** — mounted lazily on "Play preview" click (not on mount), from the build-time-resolved track id; verified "Slow Down" (`4LycrPCWsqESQ08I3ghkrT`) plays. Replaces the iTunes→Deezer player + the "Search on Apple Music" link-out (both retired, R3).
- [x] **Graceful degrade** — a song with no resolved id shows no player and no broken link (verified "Still Cookin").
- [x] **"+N more collaborations"** affordance when an edge has >3 songs.
- [x] **0-degree Kendrick** easter-egg state.
- [x] **Known-artist-no-path** state (200/null) — distinct from…
- [x] **Unknown-artist not-found** state (404).
- [x] **Gibberish → honest empty** message + disabled Find button.
- [x] **Data attribution + non-affiliation disclaimer** footer (updated: MusicBrainz + Spotify embed; Apple/Deezer retired).
- [x] **Responsive** at 375px and desktop.

### Added in plan 004 (Spotify embeds + chrome + results treatment)

- [x] **Inert Spotify-app chrome** — sidebar + top bar + profile avatar top-right wrap the feature; nav routes nowhere; verified usable inside the shell at desktop and 375px (sidebar hidden on mobile, feature never squeezed).
- [x] **Path headline / transit-line** — the chain leads the connection page ("Larry June → Dom Kennedy → Kendrick Lamar"); 1-degree and 2-degree chains verified; scrolls horizontally at 375px.
- [x] **Compact, icon-led search bar** — narrower `max-w-md`, leading search icon; typeahead / keyboard nav / auto-run / notice behavior unchanged (dumb-renders API order).

**Verification contract met (plan 004):** Python + API suite 98 green (incl. `tests/test_spotify_enrich.py`, `tests/test_api.py`); the live preview confirms the chrome, the compact search + typeahead, the path headline, the working Spotify embed ("Slow Down" plays), and graceful no-id degrade — at desktop + 375px, no console errors; **zero runtime Spotify API calls** (only the sanctioned embed iframe URL + our own `/api/*`); Streamlit app still boots on demand (untouched).

### Added in plan 007 (Path B — lazy resolve-on-Play previews)

Plan 007's feasibility spike (`scripts/preview_coverage_spike.py`) measured Spotify-id resolvability on real *displayed* songs: **best offline source ~15% (ListenBrainz) / ~4.6% (MusicBrainz links)** vs **~78% for Spotify's own search** — so the offline pre-bake pipeline (plan 005) was **not** built; the lazy path is the workhorse.

- [x] **Lazy resolve-on-Play** — a song with no resolved id shows a "Play preview" button; on click, `POST /api/resolve-preview?song_id=` runs one Spotify search, persists the id, and mounts the embed. Nothing fires on search/page-load — only on Play, once per song, cached forever after.
- [x] **Graceful degrade** — no acceptable match → "Preview unavailable" (a `"none"` sentinel is persisted so it never re-searches); no creds / network error → same, leaving the row NULL for a later retry. No broken links.
- [x] **Token cached in-process** (`_spotify_token`, ~50 min) — the client-credentials token is fetched once, not per request; `.env` is auto-loaded so `uvicorn` has creds.

> **⚠️ Pre-public guardrail (DEFERRED to the deployment plan):** `/api/resolve-preview` makes a live Spotify call and must NOT be exposed to public traffic without a global rate limit, per-IP limit, and daily budget. It is demo-safe (each song resolves at most once, then cached), but a viral spike of first-plays could approach Spotify's rolling rate window. Do not deploy publicly until those guardrails land.

### Added in plan 008 (preview waterfall + six-degrees redesign)

The Spotify iframe embed (plan 004) is **retired** as the player. Previews now come from a **waterfall** returning a directly-playable audio URL — **Spotify embed `audioPreview.url`** (reverse-engineered; spike measured 100% of resolved ids yielding a preview, 0 errors) → **iTunes `previewUrl`** → **Deezer** — played in a compact in-app `<audio>` player, uniform across sources.

- [x] **No dead Play buttons (R1)** — the edge is resolved at page-load (`/api/edge-preview`), which returns the *first song with a confirmed preview*; the card only ever renders a real inline player or, when no song on the edge has any preview, an **Apple Music search** link (verified: 3-degree Sinatra path resolved all 3 hops inline).
- [x] **Six-degrees chain (R6)** — vertical artist → compact song+player card → arrow → next artist → … → Kendrick; replaced the wide 3-song box. Compact `max-w-sm` cards.
- [x] **Kendrick anchored as the base node (R7)** — transit-line viz with Kendrick larger + solid brand-green + connectors flowing into him (no crown); searched artist + intermediates are outline pills. Scrolls horizontally at 375px, no page overflow.
- [x] **K.Dot score copy (R7)** — the degree count reads "{Artist}'s (k)dot score is: {N}", above the viz.
- [x] **Attribution updated** — footer now credits Spotify + Apple Music + Deezer (the waterfall sources).

> **⚠️ Source legality (R9):** iTunes/Deezer are sanctioned no-auth APIs. The Spotify embed `audioPreview.url` scrape is a documented community workaround — **gray-area vs. Spotify ToS**. It's gated behind a feasibility spike, kept demo-scoped, and iTunes remains a first-class non-scrape source so the app never *depends* on the scrape. Same pre-public guardrail deferral as above applies (the edge-preview endpoint makes upstream calls).

### Added in plan 009 (rich preview card + calmer flow)

The preview card now mirrors a real Spotify card, and the flow is calmer.

- [x] **Full song details** — cover + song title + credited artist line (MusicBrainz lineup, e.g. "Baby Keem, Kendrick Lamar, Sam Dew") + album + year + source label. Album/year come from the audio source; the Spotify embed lacks album, so it's **backfilled from a free iTunes metadata lookup**.
- [x] **Album-color-adaptive card** — a `dominant_color` is extracted server-side (Pillow, `src/album_color.py`) and used as the card background under a dark scrim (`linear-gradient(rgba(0,0,0,.30), rgba(0,0,0,.58)), <color>`) so white text stays legible for any cover. Bigger 72px cover + a soft drop-shadow so the card pops.
- [x] **Calmer flow** — toned down the transit-line + chain (thinner/dimmer connectors, base node without the glow ring, smaller/desaturated K.Dot number) while keeping Kendrick the clear anchored base.

> **⚠️ Year caveat (KTD3):** the year is the preview source's release date — it can reflect a reissue/compilation rather than the original collaboration (e.g. the "Topsy" comp). The authoritative original year is MusicBrainz's first-release-date, deferred (needs an ingest).
