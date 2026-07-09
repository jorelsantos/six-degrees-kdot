# Roadmap

**Current state:** **Next.js frontend + Cloudflare Worker** API (FastAPI retired to local-dev/validation tooling; the legacy Streamlit UI was retired earlier, in plan 010), SQLite-backed collaboration graph built from the **MusicBrainz** dump (CC0) — depth-3 from Kendrick Lamar, ~120k artists, 100% reachable within 3 hops, edges = shared recordings on Official releases. Every artist's shortest path is precomputed offline (`src/path_tree.py`) and served from D1 as point lookups — no live graph search in production. Artist photos via a Wikidata → TheAudioDB → Deezer waterfall (pre-baked); song previews via Spotify's official embed (no scraping). **The app is deployed at $0/month** (Cloudflare Workers + D1 free tier, Vercel free tier) — see [`docs/plans/2026-07-09-001-feat-zero-cost-public-launch-plan.md`](plans/2026-07-09-001-feat-zero-cost-public-launch-plan.md) and [`docs/RUNBOOK.md`](../RUNBOOK.md). A pytest + vitest suite covers the ingest, precompute, enrichment, and Worker logic.

This is an intentionally short list — 5-6 candidates, not a backlog. Reorder, cut, or replace items as priorities become clear. `Target` is left blank/TBD; fill it in once you've actually decided what's next rather than pre-assigning dates during a cleanup pass.

| # | Item | Why it matters | Target |
|---|------|-----------------|--------|
| 1 | Presentation polish (larger photos/names, avatar crop, motion) | Deferred from the zero-cost launch plan; the avatar object-position crop fix already landed, the rest hasn't | TBD |
| 2 | Interactivity work + real navigation (vs. non-clickable Spotify chrome) | Deferred from plans 004/010/2026-07-09-001; the public MVP prioritized shipping over polish | TBD |
| 3 | Artist-alias search (e.g. "Kanye West" → the "Ye" node) | MusicBrainz uses one canonical name per MBID; users searching a common alias currently miss the node. MB stores aliases — the Worker's FTS5 index already covers them, this is about surfacing/testing it thoroughly | TBD |
| 4 | Mobile-responsive layout pass | The UI hasn't been systematically checked on narrow viewports | TBD |
| 5 | Official-release edge filter for the precomputed path tree | Bootleg/mashup recordings occasionally create spurious edges (e.g. a Beatles→Kendrick shortcut) — accepted for the zero-cost launch, deferred as a separate graph-quality project | TBD |
| 6 | Producer/credits graph (separate work tree) | A production-credits network (producers, writers, engineers — Metro Boomin, Pharrell, etc.) reusing the same engine with a different edge type; needs its own product framing | TBD |
| ~~x~~ | ~~Automated tests for BFS correctness~~ | ✅ Done — pytest suite covers ingest, preview, and edge/dedup logic | — |
| ~~x~~ | ~~Deploy the app somewhere public~~ | ✅ Done — Cloudflare Worker + D1 + Vercel, $0/month (plan 2026-07-09-001) | — |
| ~~x~~ | ~~Expand the MusicBrainz build beyond depth 2~~ | ✅ Done — depth-3, 100% of ~120k artists reachable | — |
