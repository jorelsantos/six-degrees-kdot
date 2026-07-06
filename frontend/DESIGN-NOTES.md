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
- [x] **Data attribution preserved** — MusicBrainz (CC0), Apple Music/iTunes, Deezer, per the Streamlit footer.

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
- [x] **30s audio preview** — iTunes→Deezer, fetched on first play (not on mount).
- [x] **Store link-out** — "Listen on / Search on Apple Music".
- [x] **"+N more collaborations"** affordance when an edge has >3 songs.
- [x] **0-degree Kendrick** easter-egg state.
- [x] **Known-artist-no-path** state (200/null) — distinct from…
- [x] **Unknown-artist not-found** state (404).
- [x] **Gibberish → honest empty** message + disabled Find button.
- [x] **Data attribution + non-affiliation disclaimer** footer.
- [x] **Responsive** at 375px and desktop.

**Verification contract met:** Python suite 89 green (incl. `tests/test_api.py`), six headline UI flows screenshotted at both widths, Streamlit app still boots on demand (untouched). Broad-query latency handled via the API layer (longer debounce on short/typo queries).
