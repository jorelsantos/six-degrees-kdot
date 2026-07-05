# Roadmap

**Current state:** Streamlit web app, SQLite-backed collaboration graph built from the **MusicBrainz** dump (CC0) — depth-2 from Kendrick Lamar, ~16k artists, edges = shared recordings on Official releases. Previews via **iTunes + Deezer** (Spotify's `preview_url` is deprecated). Spotify-brand styling. **The Spotify-crawl rate-limit problem is resolved by the MusicBrainz migration** (see [`docs/plans/2026-07-04-001-feat-musicbrainz-graph-migration-plan.md`](plans/2026-07-04-001-feat-musicbrainz-graph-migration-plan.md)); the Spotify crawler is retained as a fallback. A pytest suite now covers the ingest + preview + edge logic.

This is an intentionally short list — 5-6 candidates, not a backlog. Reorder, cut, or replace items as priorities become clear. `Target` is left blank/TBD; fill it in once you've actually decided what's next rather than pre-assigning dates during a cleanup pass.

| # | Item | Why it matters | Target |
|---|------|-----------------|--------|
| 1 | Deploy the Streamlit app somewhere public (Streamlit Community Cloud or similar) | The app currently only runs locally; a public link is the difference between "a project on my machine" and something shareable. Resumes from [`docs/plans/2026-06-30-004-feat-depth3-rebuild-public-demo-plan.md`](plans/2026-06-30-004-feat-depth3-rebuild-public-demo-plan.md) against the new MB DB | TBD |
| 2 | Expand the MusicBrainz build beyond depth 2 | First iteration is intentionally capped at depth 2 (KTD5); local BFS is free, so deeper coverage is a low-cost follow-up once depth 2 is validated | TBD |
| 3 | Artist-alias search (e.g. "Kanye West" → the "Ye" node) | MusicBrainz uses one canonical name per MBID; users searching a common alias currently miss the node. MB stores aliases — surfacing them would fix the one real coverage gap found in U6 | TBD |
| 4 | Mobile-responsive layout pass | The Spotify-styled cards/track-list UI hasn't been checked on narrow viewports | TBD |
| 5 | Producer/credits graph (separate work tree) | A production-credits network (producers, writers, engineers — Metro Boomin, Pharrell, etc.) reusing the same engine with a different edge type; needs its own product framing | TBD |
| ~~x~~ | ~~Automated tests for BFS correctness~~ | ✅ Done — pytest suite now covers ingest, preview, and edge/dedup logic | — |
