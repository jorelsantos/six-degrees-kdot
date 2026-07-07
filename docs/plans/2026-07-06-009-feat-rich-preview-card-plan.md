---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
title: "feat: Rich Spotify-style preview card (artists · album · year · album-color) + calmer flow"
date: 2026-07-06
type: feat
depth: standard
---

# feat: Rich Spotify-style preview card (artists · album · year · album-color) + calmer flow

**Product Contract preservation:** No upstream brainstorm; scope confirmed live with the user (2026-07-06) from testing feedback on the plan-008 preview card. Follow-on to `docs/plans/2026-07-06-008-feat-preview-waterfall-results-redesign-plan.md` (built + shipped on `feat/preview-waterfall-results`). Anchored to `STRATEGY.md` (delight/shareability).

> **Context for a new session:** The connection page (`frontend/app/components/connection-view.tsx`) renders a vertical six-degrees chain; each hop is a `PreviewCard` (`frontend/app/components/preview-player.tsx`) that calls `/api/edge-preview` (`api/main.py`) to get the first song with a playable preview and plays it in a compact `<audio>` player. The preview comes from a waterfall (`src/preview_resolver.py`: Spotify-embed-scrape → iTunes → Deezer). Today the card shows only the song title + source label + player + a small cover — it "feels empty" vs. real Spotify cards. This plan enriches it (artists, album, year, album-color background) and calms the too-loud node viz.

---

## Summary

Two changes, both from testing feedback on the plan-008 card:

1. **Make the preview card look like a real Spotify card.** Show the full song details the user's reference screenshots have — **credited artists** ("Busta Rhymes, Kendrick Lamar"), **album name**, and **release year** — a **bigger, readable album cover**, an **album-color-adaptive background** (dominant color extracted server-side, Spotify-card style), and a subtle modern shadow so it pops. The custom in-app player stays (keeps plan-008's "no dead buttons").
2. **Calm the searched-artist → Kendrick flow.** The transit-line node viz + chain are too loud (saturated green everywhere). A moderate tone-down: quieter connectors, a softer green base node, gentler K.Dot score — on-brand but calmer.

---

## Problem Frame

- **The card feels empty.** It shows title + "Spotify" + a small cover + the audio control — none of the artist/album/year detail the real Spotify/Apple cards carry (user's reference images). It should showcase the same information.
- **Metadata is available (researched 2026-07-06):**
  - Spotify embed `__NEXT_DATA__`: `artists[]` (names) + `releaseDate.isoString` (→ year) + cover art, but **no album name**.
  - iTunes Search: `artistName`, `collectionName` (**album**), `releaseDate` (**year**), artwork — the richest single source.
  - Deezer: artist + `album.title`, no release date in the search result.
  - We already carry the **MusicBrainz lineup** (`collaborators`) on each song — the natural "Artist A, Artist B" line.
- **Album cover is too small** to read/appreciate; it should be a focal element.
- **Album-color look is feasible server-side.** Pillow 12.2 is installed → extract a dominant color from the cover and theme the card (Spotify does this natively; we mimic it to keep our controllable player + reliability rather than reinstating the iframe).
- **Year is golden but imperfect from previews.** The preview source's release date answers "when did they collaborate" for most tracks, but can be a reissue/compilation year (e.g., the "Topsy" comp). The authoritative original year is MusicBrainz's first-release-date — not in our built DB today.
- **The flow is too loud.** Brand green saturates the node viz (base node glow, green connectors/arrows) + the K.Dot number; it overwhelms.

---

## Requirements

- **R1 — Full song details:** the card shows the credited artist line (e.g., "Busta Rhymes, Kendrick Lamar"), the album name, and the release year — mirroring the reference Spotify cards. Missing fields degrade gracefully (omit, don't show blanks).
- **R2 — Bigger, readable album cover:** the cover is a prominent focal element, not a tiny thumbnail.
- **R3 — Album-color-adaptive card:** the card background is themed from the cover's dominant color (extracted server-side), darkened/gradient for text contrast, with a subtle modern shadow so it pops.
- **R4 — Collaboration year:** show the connecting song's release year from the preview source; document the reissue/compilation caveat and MusicBrainz original-year as a future refinement.
- **R5 — Calmer flow (moderate):** tone down the node viz + chain — quieter connectors, a softer green base node, gentler K.Dot — keeping the base-node semantics and brand identity, just less loud.
- **R6 — No regressions:** plan-008's "no dead buttons" holds (a card still only shows when a preview exists, or the Apple fallback); Python + API suites green; Streamlit boots.

---

## Key Technical Decisions

### KTD1 — Metadata from the richest source, iTunes backfill for the album gap
The artist line comes from the MusicBrainz `collaborators` lineup (already on the payload — the true collaboration credit). Album + year come from the audio source when present; since the **Spotify embed lacks album** (verified), backfill album (and confirm year) via a **free iTunes metadata lookup** for songs whose audio source didn't supply them. iTunes reliably carries album + year + artwork, needs no auth, and we resolve at page-load scale (a few songs), so one extra lookup is acceptable. The card renders whatever fields resolved; anything missing is omitted.

### KTD2 — Dominant album color extracted server-side (Pillow), cached
The edge-preview response carries a `dominant_color` (hex) computed server-side: fetch the cover, downscale, pick a representative/dominant color, return it; cache per artwork URL (in-process). The card uses it as a darkened gradient background for the Spotify-card look, with a text-contrast overlay + subtle shadow. Rejected client-side canvas extraction: per-CDN CORS is uneven (Spotify sends `ACAO:*` but iTunes/Deezer are unverified), so server-side is uniform and reliable. Pillow 12.2 is present.

### KTD3 — Year is the preview source's release year (proxy); MB original-year deferred
Show the release year from the audio/iTunes source. It answers the question for the common case but can reflect a reissue/compilation rather than the original collaboration (the known "Topsy"-class artifact). The authoritative fix — MusicBrainz recording/release-group first-release-date — requires an ingest/rebuild and is deferred; note the caveat rather than implying certainty.

### KTD4 — Moderate node-viz + chain tone-down
Reduce brand-green saturation and visual weight: quieter/thinner connectors, a softer base-node fill (less glow/ring), a gentler K.Dot number. Keep Kendrick clearly the anchored base and the transit-line legible — this is a calibration pass, not a redesign.

---

## Implementation Units

### U1. Enrich preview metadata + dominant color (backend)

**Goal:** `/api/edge-preview` returns the rich card data — artists, album, year, artwork, and a dominant hex color.
**Requirements:** R1, R2, R3, R4
**Dependencies:** none (extends plan-008 backend)
**Files:** `src/preview_resolver.py` (add `album`, `year`, `artists` to `ResolvedPreview`; iTunes metadata backfill), `src/preview_fetcher.py` (capture `collectionName`→album, `releaseDate`→year, Deezer `album.title`), `src/spotify_preview.py` (parse `artists[]` names + `releaseDate.isoString`→year from `__NEXT_DATA__`), `src/album_color.py` (new — Pillow dominant-color, cached), `api/main.py` (edge-preview payload: `artists`, `album`, `year`, `dominant_color`), `tests/test_preview_resolver.py`, `tests/test_album_color.py` (new), `tests/test_api.py`
**Approach:** Extend the resolver to populate `artists` (prefer the MB `collaborators` passed from the endpoint), `album`, `year` (from the audio source; backfill album/year via a free iTunes lookup when absent — notably for Spotify-sourced tracks). Add `album_color.dominant_color(image_url)` using Pillow (fetch → thumbnail → dominant/representative color → `#rrggbb`), graceful `None` + in-process cache. The edge-preview endpoint attaches `artists`/`album`/`year`/`dominant_color` alongside the existing fields; the audio URL stays re-resolved fresh (plan 008 KTD3).
**Patterns to follow:** `src/preview_fetcher.py` (graceful None, cache), `src/preview_resolver.py` waterfall, plan-008 `edge_preview` endpoint.
**Test scenarios:**
- iTunes source → `album` + `year` populated from `collectionName`/`releaseDate`.
- Spotify source (no album in embed) → album backfilled via iTunes; `year` from the embed `releaseDate`; artists from the lineup.
- Deezer source → `album` from `album.title`; missing year omitted (not a blank).
- `album_color`: a solid-red fixture image → returns a reddish hex; a fetch/parse error → `None` (no raise); second call for the same URL is cached.
- Song with no artwork → `dominant_color` None; card falls back to the neutral surface.
- `/api/edge-preview` payload includes `artists`, `album`, `year`, `dominant_color`.

### U2. Rich preview card (frontend)

**Goal:** The card mirrors a real Spotify card — bigger cover, artist line, album, year, album-color background, subtle shadow.
**Requirements:** R1, R2, R3
**Dependencies:** U1
**Files:** `frontend/app/components/preview-player.tsx`, `frontend/lib/api.ts` (extend `EdgePreview` type)
**Approach:** Bigger cover (e.g., ~64–72px, rounded). A title row + a secondary line "Artist A, Artist B · Album · Year" (omit missing parts). Background = a gradient derived from `dominant_color` (darkened for contrast) with a fallback to the neutral surface when null; add a subtle `shadow`/lift so it pops. Keep the compact `<audio>` player + the Apple-fallback branch (plan 008) intact.
**Patterns to follow:** existing `preview-player.tsx`; token styling; `frontend/AGENTS.md` (read the Next guide before writing).
**Test scenarios:** `Test expectation: none — presentational; verified in the live preview: card shows cover + artists + album + year, album-color background renders with legible text, shadow present; no-artwork + missing-field cases degrade cleanly; desktop + 375px.`

### U3. Calmer node viz + chain (frontend)

**Goal:** Tone down the searched-artist → Kendrick flow (moderate).
**Requirements:** R5
**Dependencies:** none
**Files:** `frontend/app/components/path-headline.tsx`, `frontend/app/components/connection-view.tsx`
**Approach:** Reduce brand-green saturation/weight: thinner/quieter connectors + arrowheads, a softer base-node fill (drop the glow ring or soften it), a gentler K.Dot number (smaller or less-saturated). Keep Kendrick the clear anchored base and the line legible at 375px.
**Patterns to follow:** current `path-headline.tsx` transit-line; tokens in `frontend/app/globals.css`.
**Test scenarios:** `Test expectation: none — presentational; verified visually: calmer than before, Kendrick still reads as base, legible at desktop + 375px.`

### U4. Verification pass

**Goal:** Prove the rich card + calmer flow work end-to-end without regressions.
**Requirements:** R1–R6
**Dependencies:** U1–U3
**Files:** `tests/` (suite), `frontend/DESIGN-NOTES.md`
**Approach:** Full Python + API suite green. Live preview (desktop + 375px): cards show artists + album + year over an album-color background with a shadow; the flow reads calmer; no dead buttons; Streamlit boots. Record the year caveat (KTD3) in DESIGN-NOTES.
**Test scenarios:** engine/API assertions in the suite; UI flows as the screenshot protocol.

---

## Scope Boundaries

**In scope:** rich card metadata + dominant color (U1), the rich card UI (U2), the calmer flow (U3), verification (U4).

### Deferred to Follow-Up Work
- **MusicBrainz original collaboration year** (first-release-date) — authoritative vs. the preview source's reissue/compilation year (KTD3); needs an ingest/rebuild.
- **Public-deployment guardrails** — still deferred (the edge-preview endpoint now also does an iTunes metadata lookup + an image fetch per new song; demo-safe, cached).
- **Reinstating the actual Spotify iframe card** — rejected in favor of mimicking (keeps the controllable player + reliability).

### Outside this plan's identity
- Reopening settled data decisions (MusicBrainz source, depth-3) or the preview waterfall itself (plan 008).

---

## Open Questions

- **Q1 (color contrast):** Some album colors are very light/dark — does the darkened-gradient + overlay always keep text legible, or do we need a per-color luminance clamp? Recommend a luminance floor/ceiling on the derived color; tune in the live preview. *Execution-time.*
- **Q2 (album backfill cost):** Always iTunes-backfill album for Spotify-sourced tracks, or only when the card is actually rendered? Recommend backfilling during edge-preview resolution (already at page-load); revisit if latency shows. *Execution-time.*

---

## Risks & Dependencies

- **Extra upstream calls (iTunes metadata + image fetch) per new song.** Adds page-load latency. Mitigated: cached (color per artwork URL; ids/source persisted from plan 008), few songs per path, demo-scoped. Same pre-public guardrail deferral.
- **Dominant-color legibility.** A poorly-chosen color can wash out text. Mitigated by the darken/overlay + a luminance clamp (Q1).
- **Year accuracy (KTD3).** Preview-source year can misattribute (reissue/comp). Mitigated by documenting it; MB original-year deferred.
- **Next.js caveat (`frontend/AGENTS.md`)** — read the bundled guide before frontend edits.

---

## Verification Contract

1. Python + API suites green (no regression from plans 001–008); Streamlit boots (R6).
2. `/api/edge-preview` returns `artists`, `album`, `year`, `dominant_color`; iTunes backfills album for a Spotify-sourced track; `album_color` degrades to None on error (R1, R3, R4).
3. Live preview (desktop + 375px): the card shows a bigger cover + artist line + album + year over an album-color background with a subtle shadow; missing fields omit cleanly; no dead buttons (R1–R3, R6).
4. The node viz + chain read calmer while Kendrick still reads as the anchored base (R5).
5. DESIGN-NOTES records the year caveat.

## Definition of Done

- The preview card showcases artists + album + year over an album-color-adaptive background with a bigger cover and a subtle shadow — like the reference Spotify cards; missing fields degrade gracefully (R1–R4).
- The searched-artist → Kendrick flow is moderately calmer while keeping Kendrick as the anchored base (R5).
- Suites green; Streamlit boots; no dead buttons; year caveat + MB original-year refinement recorded (R6).

---

## Sources & Research

- **Live field probes (2026-07-06):** Spotify embed `__NEXT_DATA__` carries `artists[]` + `releaseDate.isoString` (year) + cover art but **no album**; iTunes Search carries `artistName` + `collectionName` (album) + `releaseDate` (year) + artwork; Deezer search carries artist + `album.title` (no release date). Pillow 12.2 installed (server-side color OK); Spotify image CDN returns `access-control-allow-origin: *` (client canvas would also work, but server-side chosen for uniformity).
- **Reference cards (user, 2026-07-06):** Apple/Spotify cards showing cover + "Artist A, Artist B" + album + the color-adaptive background this plan mimics.
- **Existing code:** `src/preview_resolver.py`, `src/preview_fetcher.py`, `src/spotify_preview.py` (plan 008), `frontend/app/components/preview-player.tsx`, `path-headline.tsx`, `connection-view.tsx`.
- **Prior plans:** 008 (the card/waterfall this enriches), 007 (lazy resolution), `STRATEGY.md`. Memory: [preview sources reverse-engineered](/Users/jojo/.claude/projects/-Users-jojo-Documents-projects-six-degrees-kdot/memory/preview-sources-reverse-engineered.md).
