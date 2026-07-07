---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
title: "feat: Preview-sourcing feasibility spike — is the offline pipeline worth building, or lazy-only?"
date: 2026-07-06
type: feat
depth: standard
---

# feat: Preview-sourcing feasibility spike — is the offline pipeline worth building, or lazy-only?

> **SPIKE RESULT — PATH B (2026-07-06, spike actually run).** The measurement ran on **67 real displayed songs** across 25 famous cross-genre targets (see Findings below). Offline sources fall far below the go/no-go floor — **ListenBrainz-metadata 14.9%**, MB URL links ~4.6% — while **Spotify's own search (the lazy path) resolves 77.6%** of the *same* songs (5×), with the ~22% misses concentrated in obscure/novelty/spurious edges. **Decision: ship lazy-resolve-on-Play + persist as the workhorse (Path B), with Deezer-by-ISRC as the non-Spotify fallback. Do NOT build plan 005's offline pipeline** — offline pre-baking isn't worth the 7-unit build. This **supersedes** the earlier "build the full stack" lean recorded below.
>
> **Prior lean (superseded):** an earlier session had resolved to build the full source waterfall (MB links → ISRC → ListenBrainz → Wikidata → lazy) in `docs/plans/2026-07-06-005-...-plan.md`. The spike's hard data (above) reverses that: the offline layers earn too little to justify the build.

**Product Contract preservation:** No upstream brainstorm; scope confirmed live with the user (2026-07-06). Originally a **gating spike** for `docs/plans/2026-07-06-005-...-plan.md`; the gate resolved to "build the full stack" (see the DECISION note above). Anchored to `STRATEGY.md` (delight-over-completeness; the demo only needs previews for songs people actually view).

> **Context:** Rabbit Hole plays connecting-song previews via the Spotify **embed** (a track id alone plays a 30s preview — plan 004, verified). Plan 005 proposed sourcing track ids offline from the MusicBrainz dump to avoid crawling Spotify's rate-limited search API. Before building plan 005's multi-unit pipeline, this spike measures whether offline coverage is high enough to be worth it — or whether a much simpler **lazy-resolve-on-Play + persist** approach is the right call.

---

## Summary

Measured this session: offline Spotify-id coverage of our graph is **low** — MusicBrainz's own Spotify links cover only **4.6%** of our connecting recordings, and even counting ISRC the offline-resolvable ceiling is **~28.7%**, leaving a **~71% gap**. Quick probes of ListenBrainz's MBID→Spotify mapping were **inconclusive** (biased samples returned single digits). Wikidata's track-level Spotify coverage is thin.

The strategic consequence: **no offline source cleanly solves the preview problem.** But it doesn't have to — the app only shows songs on *viewed* paths, so **lazy-resolve-on-Play + persist** (resolve a song's id the first time someone plays it, then cache it forever) is the real workhorse, and it's demo-safe (a few resolutions total, each once). This spike runs one proper, unbiased coverage measurement to decide between two paths, then commits to the simpler one that fits the real numbers.

---

## Findings & Decision (spike run 2026-07-06)

**Method:** `scripts/preview_coverage_spike.py` resolved 25 famous cross-genre search targets (rap/pop/R&B/rock/older acts), ran the real shortest-path finder to Kendrick, and collected the **deduped songs the UI actually displays** (≤3 per edge) → **67 unique displayed songs**. Each was measured for Spotify-id resolvability per source. This avoids the raw-degree-hub sampling trap (Various Artists / Hatsune Miku).

| Source | Resolvable (of 67 displayed songs) | Notes |
|---|---|---|
| **Spotify search** (the lazy path) | **52 = 77.6%** | Spotify's own fuzzy search + accept-logic; misses mostly obscure/novelty/spurious edges |
| **ListenBrainz** (`spotify-id-from-metadata`, artist+title) | **10 = 14.9%** | best offline source; strict artist-primary match hurts on "feat." credits |
| **MusicBrainz** URL links | ~4.6% | session dump scan (needs recording MBIDs to measure per-song) |

**Decision (KTD2, 60/40 rule): PATH B — lazy-resolve-on-Play + persist.** The best offline source (14.9%) is far below the 40% floor, while the lazy path (77.6%) resolves ~5× as many displayed songs and is exactly the mechanism plan 004 already proved (`spotify_enrich`). Offline pre-baking (plan 005's 7 units) is **not worth the build**. Ship the trimmed lazy path (U3) + Deezer-by-ISRC as the non-Spotify fallback for the ~22% Spotify-search misses (many of which are spurious edges anyway).

**Implication for plan 005:** superseded down to its lazy tail (U8) + graceful multi-source rendering (U5). The offline extraction/ingest/backfill units (U1–U4, U6) are dropped as not cost-justified. Plan 005 is marked `superseded` accordingly.

**SHIPPED (2026-07-06):** U3 (the trimmed lazy path) is built and verified. `POST /api/resolve-preview` runs one Spotify search on first Play, persists the id (or `"none"` sentinel), and caches it; the frontend resolves lazily on Play and degrades to "Preview unavailable" on a miss. In-process token cache + `.env` auto-load added. 104 tests green; live-verified a hit (Baby Keem × Kendrick "Family Ties" → embed mounts), the degrade path, persistence (no re-search), and Streamlit still boots. Pre-public guardrails deferred (see `frontend/DESIGN-NOTES.md`).

---

## Problem Frame

- **Offline coverage is lower than hoped (measured, solid):** of 1,396,847 recordings connecting ≥2 of our 119,729 artists — Spotify link **4.6%** (63,632), ISRC **28.6%** (399,199), either **28.7%** (400,569), gap **71.3%** (996,278). Global co-credited floors were 3.1% / 20.3%; our prominent graph is higher but still far from "mostly covered."
- **ISRC ≠ Spotify player.** ISRC (28.6%) resolves to a Deezer preview (free) or needs a rate-limited Spotify `isrc:` search to get a Spotify track id. So the "Spotify-embed-playable offline" number is really the **4.6%**.
- **ListenBrainz probe inconclusive.** `spotify-id-from-mbid` and `spotify-id-from-metadata` (labs.api.listenbrainz.org) returned single-digit hit rates — but both samples were biased (insertion-order-obscure recordings; then raw-degree "hubs" like Various Artists / Hatsune Miku, which are not the pop songs the app surfaces). A proper, popularity-weighted probe on *actually-displayed* songs is needed before trusting or dismissing it.
- **The app doesn't need most songs resolved.** It shows ≤3 songs per edge on viewed shortest paths. The 71% gap is mostly songs no one will ever see — pre-resolving them is wasted work. Lazy resolution touches only viewed songs.
- **Build cost is real.** Plan 005 is 7 units (offline index, ingest plumbing, backfill, ISRC gap-fill, multi-source UI, lazy tail, verification). If offline coverage is ~5–30%, most of that machinery earns little; a lazy-only approach is a fraction of the work.

---

## Requirements

- **R1 — Unbiased coverage measurement:** measure Spotify-id resolvability on a **popularity-weighted** sample of songs the app *actually displays* (deduped canonical songs on real shortest paths from Kendrick), across all candidate offline sources (MB links, ISRC→Deezer, ListenBrainz MBID endpoint, ListenBrainz metadata endpoint).
- **R2 — Decision, not just data:** the spike ends with a committed path — **A) build the offline pipeline (plan 005)** or **B) ship lazy-only** — with the coverage threshold that drove it recorded.
- **R3 — No premature build:** do not build plan 005's offline units until this spike clears; do not over-engineer if the numbers say lazy-only.
- **R4 — Reuse, don't rebuild:** the spike reuses existing dump-extract scripts and the `spotify_enrich` search seam; it must not require a graph rebuild.

---

## Key Technical Decisions

### KTD1 — Lazy-resolve-on-Play + persist is the presumptive primary
Given the measured 71% gap, the default architecture is: resolve a song's Spotify id on first Play (via `spotify_enrich.search_track` + accept-logic), persist it, done. Only viewed songs ever resolve; each resolves once, ever; cached forever. This is demo-safe and far simpler than the offline pipeline. Offline sourcing is now a *coverage booster* (instant zero-call previews for the slice it covers), not the foundation — a reversal of plan 005's framing, driven by the coverage data.

### KTD2 — One proper coverage spike gates the offline investment
Before building plan 005's offline units, measure real resolvability on a popularity-weighted sample of displayed songs across all sources. Decision rule: if a **single offline source clears ~60%** on displayed songs (esp. ListenBrainz-via-metadata, which matches Spotify's real catalog), build the offline pipeline with that source primary. If the best offline source is **<~40%**, ship lazy-only and drop plan 005's heavy units. The 40–60% band is a judgment call weighed against build cost.

### KTD3 — Prefer ListenBrainz metadata endpoint over MB URL relationships if it wins
MB's contributor-added URL links (4.6%) are weak. ListenBrainz's `spotify_metadata_index` is built by matching Spotify's actual catalog to MB, so on *popular* songs it may be far higher — but only the spike (R1) settles it. If it wins, it becomes the offline source and MB-URL extraction is dropped. It's a MetaBrainz API (CC0, gentle limits, no Spotify dev-quota) — batchable, not a Spotify crawl.

### KTD4 — Deezer-by-ISRC is the non-Spotify fallback, not a Spotify-id source
ISRC's 28.6% mostly buys a *Deezer* preview, not the Spotify player. Keep it as a graceful fallback (the user accepted Apple/SoundCloud/Deezer fallbacks), but don't count it toward "Spotify-embed coverage."

---

## Implementation Units

### U1. Popularity-weighted coverage spike across all sources

**Goal:** One defensible measurement of Spotify-id resolvability on songs the app actually displays, per source.
**Requirements:** R1, R4
**Dependencies:** none (dump tables already extracted to `data/mb_raw/mbdump/`)
**Files:** `scripts/preview_coverage_spike.py` (new), `docs/plans/2026-07-06-007-...-plan.md` (record results back into this plan's Findings)
**Approach:** Build the sample the *right* way: run the existing shortest-path finder for a basket of realistic search targets (a curated list of famous cross-genre artists — the demo's actual traffic), collect the deduped connecting songs actually shown (≤3/edge), and de-duplicate. For each song measure resolvability via: (a) MB Spotify link (needs recording MBID — approximate via title+lineup match or accept as "known 4.6%"), (b) ListenBrainz `spotify-id-from-metadata` (artist+title — the batchable, catalog-matched source), (c) ListenBrainz `spotify-id-from-mbid` where a recording MBID is available, (d) Deezer `/track/isrc:` for ISRC'd songs. Report per-source hit rate and the union ceiling. Rate-limit the API calls; bounded sample (~300–500 songs).
**Patterns to follow:** `src/path_finder_sqlite.py` (get real displayed songs), `src/spotify_enrich.py` (accept-logic), the session's dump-scan scripts.
**Execution note:** This is a measurement spike, not production code — clarity over polish; print a clear per-source table.
**Test scenarios:** `Test expectation: none — measurement spike; correctness is the sanity of the sample (real displayed songs, popularity-weighted) and reproducible counts.` Verify: the sample is drawn from real shortest-path songs (not raw-degree hubs); per-source percentages printed; union ceiling computed.

### U2. Decision gate — commit to a path

**Goal:** Turn the U1 numbers into a committed build decision.
**Requirements:** R2, R3
**Dependencies:** U1
**Files:** this plan (record the decision + threshold), and either mark plan 005 "go" or supersede it.
**Approach:** Apply KTD2's rule. **Path A (offline pipeline worth it):** best offline source ≥~60% on displayed songs → proceed with plan 005, swapping in the winning source (likely ListenBrainz-metadata) as primary; keep lazy as the tail. **Path B (lazy-only):** best offline source <~40% → supersede plan 005's offline units; ship a trimmed lazy-resolve-on-Play + persist (see U3) plus Deezer-by-ISRC fallback; record that the offline pre-bake wasn't worth the build. Record the numbers and the choice in this plan.
**Test scenarios:** `Test expectation: none — decision record.`

### U3. (Conditional, Path B) Trimmed lazy-resolve-on-Play + persist

**Goal:** If the gate picks lazy-only, ship the minimal workhorse.
**Requirements:** R3 (KTD1)
**Dependencies:** U2 = Path B
**Files:** `api/main.py` (resolve-on-Play endpoint: one `spotify_enrich.search_track` + persist), `frontend/app/components/spotify-embed.tsx` (call it on Play when unresolved), optionally Deezer-by-ISRC fallback, `tests/test_api.py`
**Approach:** On Play for an unresolved song, resolve one id via search + accept-logic, persist (`set_spotify_track_id`), render the embed; a second view reads the cache. This is plan 005's U6 promoted to the primary (and only) resolution path. Document the pre-public guardrail requirement (rate limit, budget, per-IP) as deferred to the deployment plan.
**Test scenarios:**
- Unresolved song → resolve endpoint returns + persists an id (mocked search); second call makes no search.
- Miss → persists `"none"`, degrades to no player (or Deezer fallback if ISRC present).
- `DESIGN-NOTES.md` records the pre-public guardrail deferral.

---

## Scope Boundaries

**In scope:** the coverage spike (U1), the decision (U2), and — only if the decision is Path B — the trimmed lazy path (U3).

### Deferred to Follow-Up Work
- **The full offline pipeline** (`docs/plans/2026-07-06-005-...-plan.md`) — built only on a Path A decision, with the winning source swapped in.
- **Public-deployment guardrails** — rate limit, budget, per-IP, token caching, CDN. The lazy path is demo-safe only.
- **Creative enrichment roadmap** — `docs/plans/2026-07-06-006-...-plan.md`, unaffected by this decision.

### Outside this plan's identity
- Reopening settled data decisions (MusicBrainz source, Official-only edges, depth-3).
- Building a bespoke audio player (Spotify embed + minimal fallback only).

---

## Open Questions

- **Q1 (threshold):** Is ~60%/~40% the right go/no-go band, or should build-cost tip it lower? Recommend deciding *after* seeing U1's spread. *Resolved at U2.*
- **Q2 (ListenBrainz batch limits):** What throughput does the labs API tolerate for a real (Path A) run? Measure politely in U1. *Execution-time.*
- **Q3 (recording MBID for MB-link source):** Path A likely needs recording MBIDs (plan 005 KTD2) — fold into the next graph rebuild vs. title+lineup backfill. *Deferred to plan 005 if Path A.*

---

## Risks & Dependencies

- **Spike sample bias (the very trap hit this session).** Raw graph degree surfaces compilation hubs, not pop. Mitigation: draw the sample from real shortest-path displayed songs for famous search targets, not `ORDER BY degree`.
- **ListenBrainz metadata matching is fuzzy.** Empty `release_name` and name normalization hurt hit rate. Mitigation: pass artist+title (and release when available) and reuse accept-logic; treat the number as a floor.
- **Over-building risk (the user's stated concern).** Mitigation: this spike exists precisely to avoid building plan 005's 7 units if the coverage doesn't justify it.

---

## Verification Contract

1. U1 prints a per-source coverage table on a popularity-weighted sample of **real displayed songs** (not degree hubs), with a union ceiling.
2. U2 records a committed Path A/B decision and the threshold that drove it, in this plan.
3. If Path B: Python + API suites green; lazy resolve-on-Play persists and never re-searches a cached song; Streamlit still boots.

## Definition of Done

- Real Spotify-id resolvability is measured per source on displayed songs (R1).
- A committed decision — build the offline pipeline (plan 005) or ship lazy-only — is recorded with its rationale (R2).
- No offline machinery was built ahead of that decision (R3); if Path B, the trimmed lazy path is shipped and green.

---

## Sources & Research

- **Session measurements (2026-07-06):** our graph = 119,729 artists; 1,396,847 connecting recordings; Spotify-link 4.6% (63,632), ISRC 28.6% (399,199), either 28.7% (400,569), gap 71.3%. Global co-credited floors: 3.1% Spotify / 20.3% ISRC.
- **ListenBrainz labs** (`labs.api.listenbrainz.org`): `spotify-id-from-mbid` and `spotify-id-from-metadata` endpoints (POST JSON array; returns `spotify_track_ids`). Built from `mapping.spotify_metadata_index` (Spotify catalog matched to MB). CC0, MetaBrainz-friendly. Quick biased probes: single-digit hit rates — inconclusive, needs U1.
- **Wikidata** P2207 (Spotify track ID) + P4404 (MB recording ID) — CC0, bulk-downloadable, but track-level coverage is thin (strong at artist-level P1902 only).
- **MetaBrainz datasets** (`metabrainz.org/datasets`): canonical MB dump + PostgreSQL/JSON dumps; **no** bulk Spotify-mapping download — the mapping is API-only via labs.
- **Deezer** `GET api.deezer.com/track/isrc:{isrc}` — free ISRC→preview (non-Spotify fallback).
- **Companion plans:** 005 (offline pipeline — gated by this spike), 006 (creative roadmap). Memory: [MusicBrainz dump enrichment goldmine](/Users/jojo/.claude/projects/-Users-jojo-Documents-projects-six-degrees-kdot/memory/musicbrainz-dump-enrichment-goldmine.md).
