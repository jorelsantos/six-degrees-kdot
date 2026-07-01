# Roadmap

**Current state:** Streamlit web app, SQLite-backed collaboration graph (~27k artists pre-built from Kendrick Lamar), Spotify-brand styling, working audio previews. Legacy CLI/pickle stack removed (see [`docs/plans/2026-06-30-001-refactor-repo-cleanup-restart-plan.md`](plans/2026-06-30-001-refactor-repo-cleanup-restart-plan.md)).

This is an intentionally short list — 5-6 candidates, not a backlog. Reorder, cut, or replace items as priorities become clear. `Target` is left blank/TBD; fill it in once you've actually decided what's next rather than pre-assigning dates during a cleanup pass.

| # | Item | Why it matters | Target |
|---|------|-----------------|--------|
| 1 | Automated tests for `src/path_finder_sqlite.py`'s BFS correctness | No test suite exists today; the path-finding logic is the core value of the app and currently has zero regression protection | TBD |
| 2 | Live-lookup path for artists outside the pre-built network | Right now an artist not already in the ~27k-artist graph may return "no path" even if one exists; a bounded live-expansion fallback would make results more trustworthy | TBD |
| 3 | Deploy the Streamlit app somewhere public (Streamlit Community Cloud or similar) | The app currently only runs locally; a public link is the difference between "a project on my machine" and something shareable | TBD |
| 4 | Mobile-responsive layout pass | The Spotify-styled cards/track-list UI hasn't been checked on narrow viewports | TBD |
| 5 | Expand the pre-built network depth/breadth from Kendrick Lamar | Current network is built to a fixed depth; deeper coverage means fewer "not found" results for less mainstream artists | TBD |
| 6 | Rotate/cap the local JSON API-response cache in `data/` | 38k+ cached JSON files accumulate with no expiry-based cleanup; a simple prune-on-build step would keep local disk usage bounded | TBD |
