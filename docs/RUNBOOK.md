# Runbook: Build Pipeline & Data Refresh

**Architecture (plan [`2026-07-09-001`](plans/2026-07-09-001-feat-zero-cost-public-launch-plan.md)):** the public app is served entirely from Cloudflare's free tier — a Worker (`worker/`) reading a precomputed path tree out of D1. There is no live graph search and no server-side Spotify/audio fetching in production. Your laptop is the permanent build pipeline: it owns the MusicBrainz graph, the precompute, the offline enrichment passes, and every export. Nothing on this page runs in production; all of it runs locally, on demand.

```
MusicBrainz dump                       (build input, never deploys)
      │
      ▼
master SQLite (data/collaboration_network_mb.db, 192MB, gitignored)
      │
      ├─ src/path_tree.py         (path-tree precompute — fast, seconds)
      ├─ src/photo_prebake.py     (photo pre-bake — slow, network-bound)
      ├─ src/track_prebake.py     (track-ID pre-bake — slow, network-bound)
      │
      ▼
scripts/export_serving_db.py  →  worker/export/{serving.db, serving.sql, fts5_setup.sql}
      │
      ▼
Cloudflare D1  (wrangler d1 execute --file=)
      │
      ▼
Worker (wrangler deploy)  ◀──/api/*── Vercel (Next.js frontend)
```

---

## One-time setup

1. **Cloudflare account + wrangler auth:** `npx wrangler login` (from `worker/`).
2. **Create the D1 database:** `npx wrangler d1 create rabbit-hole-serving` — paste the returned `database_id` into `worker/wrangler.jsonc`'s `d1_databases[0].database_id`.
3. **Spotify credentials** (for the offline pre-bakes and the Worker's lazy resolve — official Web API only, client-credentials, never scraping):
   - Root `.env` (for the Python scripts): `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` (see `.env.example`).
   - Worker secrets (for the deployed Worker): `wrangler secret put SPOTIFY_CLIENT_ID` and `wrangler secret put SPOTIFY_CLIENT_SECRET`. Local `wrangler dev` reads a gitignored `worker/.dev.vars` instead (copy `worker/.dev.vars.example`).
4. **Vercel project** pointed at `frontend/`, with `API_ORIGIN` set to the deployed Worker's URL (its `workers.dev` subdomain, or a custom domain) in the project's environment variables.

## Full build, start to finish

Run everything below from the repo root unless noted. `pip install -r requirements.txt` first (now includes `pillow`, previously missing — a clean install used to crash on `album_color`'s import).

### 1. Land the type fix and confirm the frontend builds (U1)
Already landed — `cd frontend && npm run build` should be clean going forward. No action needed on a normal refresh.

### 2. Path-tree precompute (U2) — seconds, safe to run anytime
```
python3 src/path_tree.py --db data/collaboration_network_mb.db
```
Fully recomputes and overwrites every artist's `kendrick_distance` / `predecessor_id` / `via_song_id`. No network calls — pure local BFS. Runs its own validation pass (full-table invariants + a live-BFS agreement sample) and exits non-zero if anything looks wrong. **Re-run this first** after any change to the master graph, before re-running the pre-bakes below (they depend on its output).

### 3. Photo pre-bake (U3) — hours, network-bound, run in your own terminal
```
python3 src/photo_prebake.py --db data/collaboration_network_mb.db
```
Resumable (`WHERE photo_url IS NULL`) — safe to Ctrl-C and re-run. Order: batched Wikidata SPARQL → Deezer (~8 req/s) → TheAudioDB tail (~24-30/min, the slow part — budget roughly 1,800 artists/hour for whatever's left after Wikidata+Deezer). Flags: `--min-degree N` to bound scope, `--limit N` to measure a pass, `--seed-ids id1,id2,...` to force-resolve a specific set (e.g. before adding a new Tier A showcase artist — see step 6).

### 4. Track-ID pre-bake (U4) — hours, network-bound, run in your own terminal
```
python3 src/track_prebake.py --db data/collaboration_network_mb.db
```
Requires `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` in `.env`. Only resolves path-tree via-songs (≤119k, one per artist) — not the full 563k-song catalog. Paces ~4-5 req/s. On a miss, retries the next candidate song on the same collaboration edge before giving up (so a resolvable sibling song isn't lost to an unlucky first pick). Same `--limit`/`--seed-ids` flags as step 3; `--limit 20000` gets you the top-20k-by-priority tier if you don't want to run the full sweep immediately.

### 5. Serving DB export (U6) — seconds
```
python3 scripts/export_serving_db.py --db data/collaboration_network_mb.db
```
Writes `worker/export/serving.db` (for local inspection), `worker/export/serving.sql` (what actually gets imported), and `worker/export/fts5_setup.sql` (the search index, applied in a separate step below — D1 breaks if a virtual table is in the same import as the base data). **Re-run anytime** the master DB changes; it's a full rebuild every time, never a partial merge.

**Import into D1** (there is no `wrangler d1 import` subcommand, despite that being the intuitive name — `wrangler d1 execute --file=` is what actually exists, and it wants a `.sql` text file, not the binary `.db`):
```
cd worker
npx wrangler d1 execute rabbit-hole-serving --remote --file=export/serving.sql
npx wrangler d1 execute rabbit-hole-serving --remote --file=export/fts5_setup.sql
```
(swap `--remote` for `--local` to test against `wrangler dev`'s local D1 simulation first — recommended before touching the real database).

**Budget real time for this, and expect it to take two days the first time.** The full import is `serving.sql` — ~150k `INSERT`s (≈120k artists + ≈31k aliases), one per row, executed statement-by-statement. It took several minutes locally for the full dataset (not close to instant), and **D1's free tier caps writes at 100,000 rows/day**, so a full fresh import (150k rows) plus its separate FTS5 population (~150k more) *will* exceed the daily cap and stop partway. This is expected, not a failure.

**The import is designed to be safe to re-run — this is the important part.** `serving.sql` uses `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` with no surrounding transaction, so:
- If it stops for *any* reason — the daily write cap, a network blip, Ctrl-C — the rows that already landed stay put.
- To resume, **just run the exact same command again.** Already-imported rows are skipped (a skipped `INSERT OR IGNORE` is not a write, so it doesn't spend your daily budget), and only the remaining rows get inserted. There is nothing to clean up, no "table already exists" error, no duplicate rows.
- Practical cadence on the free tier: run `serving.sql` on day one (lands ~100k rows, then errors on the cap — fine), re-run it on day two (finishes the rest), then run `fts5_setup.sql` (it `DROP`s and rebuilds the search index each time, so it too is safe to re-run; it may itself need a second day for its ~150k index rows).

You can verify a run's progress at any time with `npx wrangler d1 execute rabbit-hole-serving --remote --command "SELECT COUNT(*) FROM artists"`.

Once seeded, only the lazily-resolved `via_track_id` column drifts between exports, and re-running the pre-bakes + re-export + re-import is cheap relative to the first run (unchanged rows are skipped by `INSERT OR IGNORE`).

### 6. Tier A static demo export (U5) — seconds, plus a Vercel deploy
```
python3 scripts/export_demo.py --db data/collaboration_network_mb.db
```
Reads `scripts/showcase_artists.json` (name+id pairs — edit this file to change the showcase set) and writes one JSON file per artist plus `index.json` under `frontend/public/demo/`. **Before adding a new showcase artist**, force-resolve its full chain first so the demo doesn't ship a hole:
```
# find every hop id in the new artist's chain (predecessor walk in Python/sqlite3), then:
python3 src/photo_prebake.py --db data/collaboration_network_mb.db --seed-ids <comma-separated hop ids>
python3 src/track_prebake.py --db data/collaboration_network_mb.db --seed-ids <comma-separated hop ids>
```
Then deploy `frontend/` to Vercel as usual (`vercel --prod`, or via the Vercel dashboard's Git integration) — Tier A needs no backend at all and works standalone even if the Worker/D1 side is ever down (it's also the frontend's permanent fallback landing).

### 7. Deploy the Worker (U7)
```
cd worker
npx wrangler deploy
```
Then set `API_ORIGIN` in Vercel's project environment variables to the deployed Worker's URL, and redeploy the frontend (Vercel picks up env var changes on the next build).

### 8. Cut the frontend over (U8)
Already wired — `frontend/next.config.ts`'s `/api/:path*` rewrite reads `API_ORIGIN` (default: `http://127.0.0.1:8787`, `wrangler dev`'s local port, for local development). Once step 7's `API_ORIGIN` is set in Vercel, the live site talks to the real Worker with no further frontend code changes.

---

## Local development

- **Frontend + Worker, full stack, no cloud account needed:** `cd worker && npx wrangler dev` (serves on `:8787`, using local D1 state seeded per step 5's `--local` commands) in one terminal, `cd frontend && npm run dev` in another (`:3000`, rewrites to `:8787` by default).
- **FastAPI (`api/main.py`) is local-only tooling now** — useful for exploring the live MusicBrainz graph interactively or as the BFS oracle `path_tree.py`'s validation checks itself against, but it is not what the deployed Worker uses and its response shape has not been kept in sync with the Worker's (`{degrees, path, hops}` vs. the older `{degrees, path, connections}`). Run it with `uvicorn api.main:app --port 8000` if you need it; don't point the frontend's `API_ORIGIN` at it expecting the current frontend code to render correctly.
- **`src/spotify_preview.py`** (the scraped-embed-page preview resolver) is dev-only, permanently — Spotify's anti-bot tightening blocks datacenter IPs, and it's a ToS gray area regardless. The public app instead renders Spotify's official embed iframe client-side; nothing server-side ever touches Spotify's audio.

## Known accepted gaps (see the plan's Risks & Mitigations for full context)

- **Master DB ↔ D1 drift:** the Worker's lazy `resolve-track` writes only to D1, never back to the master DB. Harmless — the master DB is regenerated from MusicBrainz + the pre-bakes, and D1 is a disposable cache layer for that one column; a re-export overwrites it without ceremony.
- **Bootleg/mashup spurious edges** (e.g. a Beatles→Kendrick connection through an unofficial mashup recording) show up in precomputed chains exactly as they would in a live BFS. An official-release edge filter is deferred, tracked in the plan's Scope Boundaries.
- **iTunes/Deezer preview fallback** for songs with no Spotify match is deferred — those hops render an honest no-player card instead.
