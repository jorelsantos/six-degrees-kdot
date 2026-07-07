---
artifact_contract: ce-roadmap/v1
artifact_readiness: roadmap
execution: none
product_contract_source: ce-plan-bootstrap
title: "Rabbit Hole — creative enrichment roadmap (MusicBrainz goldmine + adjacent data)"
date: 2026-07-06
type: feat
depth: deep
---

# Rabbit Hole — Creative Enrichment Roadmap

**What this is:** a durable, grounded roadmap of the bigger creative expansions unlocked by data we already own (the local MusicBrainz CC0 dump) plus a few free adjacent datasets. It is **not** implementation-ready — each epic here needs its own `ce-plan` before building. Its companion, `docs/plans/2026-07-06-005-feat-offline-preview-sourcing-pipeline-plan.md`, carries the ship-now work (offline preview sourcing). Both come from the same data source; they're split because they're genuinely different buckets of work. Revisit this doc when picking the next big swing.

**Grounding principle (from the user, 2026-07-06):** *don't get too optimistic — deliver high-quality work.* Every epic below names the exact data that enables it (verified present in the dump this session) and flags real cost. Most require a **graph rebuild** or new ingest passes — that is the honest price, called out per epic.

**Strategy anchor (`STRATEGY.md`):** the north star is *delight, surprise, shareability* — not completeness. Track 1 (Kendrick graph + shareable demo) is live; Track 4 (listening-pattern/sample analysis) is the original vision several epics here feed. Every epic is scored against "does it manufacture a 'no way, really?' moment."

---

## What we confirmed is in the dump (this session)

All CC0, on disk (`data/mb_raw/mbdump.tar.bz2`), extractable offline with the existing streaming-join idiom (`src/musicbrainz_ingest.py`). We currently use exactly **one** signal — shared `artist_credit` (performer co-billing). Unused and confirmed present:

| Data | Table(s) | Unlocks |
|---|---|---|
| Sampling / remix / mashup / cover | `l_recording_recording` (types: *samples material*, remix, mashup, DJ-mix, cover) | New connection type **and** structural cleanup of spurious edges |
| Producer / writer / engineer / mixer credits | `l_artist_recording`, `l_artist_release` (54/59 roles) | The production-credits graph |
| Band membership + human ties | `l_artist_artist` (*member of band*, married, sibling, teacher, founder) | Band↔member edges; human-interest flavor |
| ISRC (universal key) | `isrc` (20.3% of co-credited recordings) | Exact cross-service matching, dedup |
| Genre / area / artist type / gender / era | `genre`, `area`, `artist_type`, `gender`, `artist.begin_date` | Surprise scoring, maps, timelines, band-vs-person |
| Streaming / image URLs | `url`, `l_recording_url`, `l_artist_url` (Spotify, Apple, SoundCloud, Bandcamp, image, Wikidata/VIAF) | Previews (plan 005) + artist photos |

Adjacent free datasets (linked from MB): **Cover Art Archive** (album covers by release MBID), **Wikidata/Wikimedia Commons** (artist photos, band membership, hometown, label), **ListenBrainz** (open listen counts = a real popularity signal, plus a 2nd MB→Spotify id mapping), **Deezer** (free ISRC lookup), **AcousticBrainz** (BPM/key/mood — dump exists but stale since 2022), **Discogs** (deep hip-hop/electronic credits — more restrictive license than MB's CC0).

---

## Shared building blocks (most epics depend on these)

These are the infrastructure investments several epics reuse. Sequencing epics after the blocks they need avoids rebuilding twice.

### B1. Multi-edge-type graph (the big one)
Today an edge = performer co-credit. Extend `musicbrainz_ingest.py` to ingest additional relationship tables as **typed** edges: `sampled`, `produced`, `wrote`, `member_of`, plus the human ties. Store an edge `type` (and keep the connecting song/context per type). This is a **graph rebuild** and a schema change (edges gain a type; the app must let users pick which edge types count). It is the foundation for Epics E1, E2, E3, E6. *Cost: high. Do once, deliberately.*

### B2. Node metadata enrichment
Attach `genre`, `area` (→ country/region), `artist_type` (person/group), and `begin_date` (→ era) to artist nodes from the dump; attach **cover art** (Cover Art Archive, by release MBID) and **artist photos** (Wikidata/Wikimedia via MB's `l_artist_url` image/VIAF links). *Cost: medium; images need a fetch+cache step (rate-limit-free bulk for CAA; Wikidata is polite-crawl or dump).* Feeds E4, E5, E7, and the design upgrades.

### B3. Real popularity signal (ListenBrainz)
The current DB ranks by graph **degree** (Last.fm was never run; popularity=0 everywhere). Swap in ListenBrainz listen counts (open, bulk) keyed by MBID via the existing `popularity_enrich.py` seam. Sharpens search ranking and enables "prominence"-aware surprise scoring (E5). *Cost: low–medium; reuses an existing pass.*

---

## Epics (grounded, phased — each needs its own ce-plan)

### E1. Sampling connections — the sample rabbit hole ⭐ flagship
**Data:** `l_recording_recording` *samples material* (+ remix/cover). **Depends:** B1.
**What:** A new connection *type* — "Kendrick connects to [X] because [song] **samples** [X's track]." Sampling is catnip for music nerds and a pure delight/shareability play. Build toward a **sample-lineage tree**: pick a song → what it sampled → what sampled *it*, recursively (a genealogy of a beat). Producers' signature samples fall out of this.
**Why it wins:** samples are the quintessential "no way, really?" — exactly `STRATEGY.md`'s north star, and a fundamentally *different* graph than performer co-credit.
**Also cleans:** the same table's mashup/DJ-mix relationships identify the spurious edges the [bootleg/spurious-edges note](/Users/jojo/.claude/projects/-Users-jojo-Documents-projects-six-degrees-kdot/memory/musicbrainz-bootleg-spurious-edges.md) flags (Beatles×Kanye, the "Topsy" comp artifact) — *structurally*, not by heuristic. Two birds.
**Cost:** high (rebuild + new edge type + UI to switch/lens).

### E2. Producer / credits graph — the production rabbit hole ⭐ (user's vision)
**Data:** `l_artist_recording` / `l_artist_release` (producer, writer, engineer, mixer). **Depends:** B1.
**What (the user's stated flow):** which producers worked with Kendrick → click a producer → which *other* artists that producer worked with → their songs → and (via E1) the samples/lineage those songs draw on. A producer becomes a first-class hub with a "collaborator constellation." Optionally a mode toggle: *performers* graph vs *production* graph.
**Why it wins:** surfaces the invisible architects (Sounwave, Metro Boomin, Pharrell) fans rarely trace; deep replay value; pairs naturally with E1's sample lineage.
**Cost:** high (rebuild + typed edges + producer-centric views). Best done right after E1 since they share B1.

### E3. Band ↔ member + human-interest edges
**Data:** `l_artist_artist` (*member of band*, married, sibling, teacher, founder). **Depends:** B1.
**What:** legit band↔member edges (fixes the Beatles-vs-Paul-McCartney band/member confusion in the spurious-edges note) and *flavor* annotations on a path hop ("…who is married to…", "…bandmate of…"). Human ties make a dry chain feel like gossip.
**Why it wins:** cheap delight layered on B1; also improves correctness (band/person distinction via `artist_type`).
**Cost:** medium (given B1).

### E4. Cover art + artist photos — the design glow-up ⭐ (near-term-ish)
**Data:** Cover Art Archive (release MBID) + Wikidata/Wikimedia (artist images). **Depends:** B2 (metadata/image fetch).
**What:** album covers next to each connecting song and on the preview; artist photos as the **transit-line stations** and on an artist detail view. Turns the text chain into something screenshot-worthy.
**Why it wins:** directly serves the *shareability* metric and the LinkedIn/X launch — a visual path card is far more postable than text. Arguably the highest delight-per-effort visual upgrade, and doesn't strictly need the B1 rebuild.
**Cost:** medium (image fetch + cache + layout); can proceed independent of B1.

### E5. Surprise engine — actively hunt the "no way, really?" ⭐
**Data:** `genre` + `area` + `begin_date` (era) + B3 popularity. **Depends:** B2, B3.
**What:** score a path by *surprise* — maximal genre/era/geography distance between endpoints — and surface the most surprising connections instead of waiting for the user to stumble on them. "Kendrick → … → a 1940s big-band artist," "connected across 3 continents." Powers a **"Daily Rabbit Hole"** auto-generated share card (album art + transit line + surprise caption).
**Why it wins:** turns `STRATEGY.md`'s north star into a *feature* — the app manufactures the delight moment and hands the user a ready-to-post card.
**Cost:** medium (scoring + card rendering; B2/B3 first).

### E6. "Connect any two artists" + rabbit-hole modes
**Data:** existing graph (+ B1 for typed modes). **Depends:** none for basic; B1 for typed.
**What:** drop the Kendrick-only framing — connect *any* two artists (BFS already supports it), and let users pick the edge lens (performed / produced / sampled / same-band). "Six degrees via samples only." Also "who do they both know" (shared-collaborator intersection).
**Why it wins:** multiplies replay value and shareability; a natural step toward `STRATEGY.md` Track 3 (open-source, any-seed template).
**Cost:** low for basic any-to-any; medium once typed on B1.

### E7. Map & timeline views
**Data:** `area` (geo) + `begin_date` (era). **Depends:** B2.
**What:** plot a connection on a world map or a timeline, showing a path that spans continents or decades. A visual companion to E5's surprise framing.
**Why it wins:** another shareable visual; makes "across eras/continents" legible at a glance.
**Cost:** medium (map/timeline component + geo/era data).

### E8. Listening-pattern mode (STRATEGY Track 4, the original idea)
**Data:** E1 samples + E2 credits + B2 genre. **Depends:** E1, E2 (and a way to ingest a user's top songs).
**What:** take a user's top 20–25 songs and surface themes / shared samples / producer lineages they didn't consciously notice. The original "Rabbit Hole" concept, one level deeper than collaboration paths.
**Why it wins:** the same discovery loop applied to *your own* taste — the most personal, sticky version of the product.
**Cost:** high (depends on the sampling + credits graph, plus a top-songs input path).

---

## "Wild" ideas catalog (lower-commitment sparks)

Grounded in data we have; captured so they aren't lost. Promote any to an epic when it earns a plan.

- **Surprise-score leaderboard / hall of fame** — the farthest and the most-surprising famous connections, curated (feeds virality).
- **"Sonic morph" journeys** — a path where BPM/key/mood shifts hop-to-hop (AcousticBrainz; stale data caveat).
- **Genre-jump highlighting** — color the transit line by genre; spotlight the hop where the path leaps genres.
- **Shared-DNA songs** — songs connected by sampling the *same* source recording (a horizontal, non-artist link).
- **"Explain this hop"** — one-line human-interest annotation per edge (married / bandmate / same producer / sample), turning the chain into a story.
- **Producer signature card** — a producer's genre/area/era fingerprint + top collaborators, as a shareable card (pairs with E2/E5).
- **Era time-travel mode** — constrain paths to cross a decade boundary ("connect a Gen-Z rapper to a Motown act").
- **Embeddable widget** — a path card others can embed on their own site/blog (Track 3 adjacency).

---

## Suggested sequencing

1. **Ship offline previews first** — companion plan 005 (unblocks the current demo; no rebuild).
2. **E4 (cover art + photos)** — high shareability, independent of the big rebuild; great for the launch.
3. **B3 (ListenBrainz popularity)** — cheap ranking win, reuses an existing pass.
4. **B1 (multi-edge-type graph)** — the deliberate foundation; do once.
5. **E1 → E2 (sampling → producer rabbit holes)** — the flagship concept expansions, both on B1.
6. **E3, E5, E6, E7** — layer on once B1/B2/B3 exist.
7. **E8 (listening-pattern mode)** — the deepest, last; needs E1+E2.

Public deployment (guardrails, hosting) remains its own deferred track (see plan 005's deferral + `STRATEGY.md` Track 1).

---

## Risks & honest caveats

- **Most epics require a graph rebuild (B1).** Rebuilds are heavy and run in the user's terminal; batch epics behind B1 rather than rebuilding per-feature.
- **Coverage varies by data type.** Sampling/producer relationships are contributor-added and uneven (strong for popular Western pop/hip-hop, thin elsewhere). Set expectations per-epic during its own `ce-plan`; lean on the delight-over-completeness approach — a rich *enough* subgraph beats an exhaustive one.
- **New edge types re-open spurious-edge risk.** Producer/sample edges bring their own noise (compilations, misattributions). E1 helps clean some structurally, but each new edge type needs its own guard pass — coordinate with the [spurious-edges note](/Users/jojo/.claude/projects/-Users-jojo-Documents-projects-six-degrees-kdot/memory/musicbrainz-bootleg-spurious-edges.md).
- **Image/licensing hygiene.** Cover Art Archive is CC-friendly; Wikidata images are mostly CC but per-image licenses vary — attribute correctly (extends the `frontend/DESIGN-NOTES.md` legal checklist). Discogs data has a more restrictive license than MB's CC0 — prefer MB where possible.
- **Scope discipline.** This is a menu, not a commitment. Each epic gets its own `ce-plan` with real requirements, tests, and a scoped rebuild — don't let the roadmap's breadth pull the near-term demo off course.

---

## Sources & Research

- **Session dump inspection (2026-07-06):** relationship-type catalog from `data/mb_raw/mbdump/link_type` (artist→recording 54 roles incl. producer; recording→recording incl. *samples material*, remix, mashup, DJ-mix; artist→artist incl. *member of band*); confirmed presence of `l_artist_recording`, `l_recording_recording`, `l_artist_artist`, `l_artist_work`, `genre`, `area`, `artist_type`, `gender`. Coverage: 890,679 Spotify track URLs; 824,670 recordings with a Spotify link (3.1% of co-credited); ISRC on 20.3% of co-credited recordings.
- **Companion plan:** `docs/plans/2026-07-06-005-feat-offline-preview-sourcing-pipeline-plan.md` (ship-now offline previews).
- **`src/musicbrainz_ingest.py`:** the streaming set-based join to extend for typed edges (B1).
- **Memories:** [producer/credits graph idea](/Users/jojo/.claude/projects/-Users-jojo-Documents-projects-six-degrees-kdot/memory/producer-credits-graph-idea.md) (E2), [bootleg/spurious-edges](/Users/jojo/.claude/projects/-Users-jojo-Documents-projects-six-degrees-kdot/memory/musicbrainz-bootleg-spurious-edges.md) (E1 cleanup), [Spotify→MusicBrainz pivot](/Users/jojo/.claude/projects/-Users-jojo-Documents-projects-six-degrees-kdot/memory/spotify-to-musicbrainz-pivot.md).
- **External datasets:** Cover Art Archive (`coverartarchive.org`, by release MBID), Wikidata/Wikimedia Commons (artist images via MB `l_artist_url`), ListenBrainz (listen counts + MB→Spotify mapping), Deezer API, AcousticBrainz (stale), Discogs (restrictive license).
- **`STRATEGY.md`:** Tracks 1 (graph + demo), 3 (open-source any-seed), 4 (listening-pattern) — E6/E8 extend 3/4.
