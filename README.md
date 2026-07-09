# Six Degrees of Kendrick Lamar ("Rabbit Hole")

A web app that finds the shortest collaboration path between any artist and Kendrick Lamar — degrees of separation, the connecting path, artist photos, and an official Spotify preview at each step. The collaboration graph is built from the **MusicBrainz** database dump (CC0). The public app runs at **$0/month**: a **Cloudflare Worker** serves a precomputed path tree out of **D1**, and the **Next.js** frontend deploys to **Vercel** — no always-on server, no live graph search, no server-side Spotify audio fetching. See [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for the full build/deploy pipeline and [`docs/plans/2026-07-09-001-feat-zero-cost-public-launch-plan.md`](docs/plans/2026-07-09-001-feat-zero-cost-public-launch-plan.md) for why.

Inspired by "Six Degrees of Kevin Bacon," this project explores how artists in hip-hop and music are connected through their collaborations.

> **Project history:** this started as a University of Michigan SI 507 course final project (a terminal CLI app). The original course writeup is archived at [`docs/archive/`](docs/archive/). It was then rebuilt as a Streamlit web app, then replatformed to Next.js + FastAPI (Streamlit retired), and now to Next.js + a Cloudflare Worker (FastAPI retired to local-dev/validation tooling — see Architecture below). This README reflects the current app.

## How It Works

1. **Enter any artist name** (e.g., "Drake", "SZA", "Taylor Swift")
2. **Get instant results** showing:
   - Degrees of separation from Kendrick Lamar
   - The connection path (Artist A → Artist B → Kendrick), with each artist's photo
   - The specific song connecting each pair, rendered as an official, playable Spotify embed

A curated static demo (no backend at all) is also available at `/demo` — a handful of showcase artists with everything pre-baked into static JSON, for a portfolio-friendly click-through that never depends on the live backend being up.

## Quick Start (local dev)

```bash
# 1. Clone and install
git clone https://github.com/jorelsantos-um/six-degrees-kdot.git
cd six-degrees-kdot
pip install -r requirements.txt          # Python engine + build-pipeline deps
(cd frontend && npm install)             # Next.js frontend deps
(cd worker && npm install)               # Cloudflare Worker deps

# 2. Run the Worker + frontend (mirrors production; no Cloudflare account needed locally)
(cd worker && npx wrangler dev)          # Worker on :8787, local D1 (terminal 1)
(cd frontend && npm run dev)             # UI at http://localhost:3000 (terminal 2)
```

Open http://localhost:3000 — the frontend proxies `/api/*` to the Worker on `:8787` by default. Seeding local D1 with real data requires running the export pipeline first — see [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

**Alternative: FastAPI local dev.** `api/main.py` still works against the live MusicBrainz graph directly (`uvicorn api.main:app --port 8000`, then set `API_ORIGIN=http://127.0.0.1:8000`) — useful for exploring the graph or debugging the engine, but its response shape isn't kept in sync with the Worker's, so the current frontend won't render correctly against it out of the box.

## Rebuilding the Network (Optional)

The graph is built from a local MusicBrainz core-data dump (CC0, no rate limit):

```bash
# 1. Download + stage the dump subset (multi-GB; ~30-40 GB extracted)
bash scripts/fetch_musicbrainz_dump.sh

# 2. Build the depth-2 collaboration graph into a new SQLite DB
python3 src/musicbrainz_ingest.py \
    --mbdump data/mb_raw/mbdump \
    --out data/collaboration_network_mb.db --depth 2
```

Edges come only from shared-recording co-credits on **Official** releases (bootleg/mashup and interview/spokenword releases are filtered out). The legacy Spotify crawler (`src/build_network_sqlite.py`) is retained as a fallback but is no longer the primary build path.

## Features

### Shortest Path Finding
- Every artist's shortest path to Kendrick is **precomputed once, offline** (a single-source BFS from Kendrick over the whole graph) and served as a handful of indexed point lookups — no live graph search in production
- Each artist node shows a resolved photo (Wikidata → TheAudioDB → Deezer waterfall, pre-baked)
- Each connecting song renders as an official Spotify embed — no server-side audio fetching, no scraping

### Data Quality
- Includes both primary albums and guest features
- Smart track filtering for guest appearances
- Prioritizes studio albums over singles
- Deduplicates collaborators case-insensitively and dedups recording versions to a canonical connecting song
- Edges restricted to shared recordings on **Official** releases (excludes bootleg/mashup, interview/spokenword, and DJ-mix blends) — with a known exception (see Troubleshooting)

## Architecture

**Production (public app):**
- **`worker/`** — Cloudflare Worker (TypeScript). The only thing public traffic hits: `GET /api/search` (FTS5 over D1), `GET /api/connection` (walks the precomputed path tree), `POST /api/resolve-track` (lazy, rate-limited Spotify track-ID resolve via the official Web API — never scraping).
- **D1** — the slim serving database (`scripts/export_serving_db.py`'s output), one denormalized row per artist.
- **`frontend/`** — Next.js app, deployed to Vercel. `/api/*` rewrites same-origin to the Worker (`next.config.ts`, `API_ORIGIN`). `/demo` is a fully static, zero-backend showcase route.

**Build pipeline (local only — see [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for the full sequence):**
- **`src/musicbrainz_ingest.py`** — Builds the master collaboration graph from the staged MusicBrainz dump into `data/collaboration_network_mb.db`.
- **`src/path_tree.py`** — Precomputes the shortest-path tree from Kendrick (distance, predecessor, connecting song per artist).
- **`src/photo_prebake.py`**, **`src/track_prebake.py`** — Offline enrichment passes (artist photos; Spotify track IDs for connecting songs).
- **`scripts/export_serving_db.py`**, **`scripts/export_demo.py`** — Produce the D1 import and the static demo JSON, respectively.
- **`api/main.py`** — FastAPI engine. **Local dev / validation tool only** — the BFS oracle `path_tree.py` checks itself against, and a way to explore the live graph interactively. Not what production serves.
- **`src/database.py`**, **`src/path_finder_sqlite.py`**, **`src/preview_fetcher.py`**, **`src/spotify_preview.py`** — Engine internals used by the build pipeline and by `api/main.py`'s local dev server.
- **`src/build_network_sqlite.py`**, **`src/data_fetcher.py`** — Legacy Spotify crawler + API client, retained as a historical fallback; not used by the current build path.

### Data Model
- **Nodes**: Artists keyed on **MusicBrainz ID (MBID)**, with a display name, resolved photo, and (in the serving DB) precomputed distance/predecessor/connecting-song fields
- **Edges**: Collaborations between artists
- **Edge Attributes**: Songs they collaborated on

## Requirements

- **Local dev:** Python 3.7+, Node.js (frontend + Worker)
- **Deployment:** a Cloudflare account (Workers + D1, free tier) and a Vercel account (free tier); Spotify API credentials (official Web API, client-credentials — used only for the offline track-ID pre-bake and the Worker's lazy resolve, never for scraping)
- Python dependencies: `requests`, `python-dotenv`, `rapidfuzz`, `fastapi`, `uvicorn`, `pillow` (see `requirements.txt`); frontend deps via `frontend/package.json`; Worker deps via `worker/package.json`

## Troubleshooting

### "Database not found"
- The app expects `data/collaboration_network_mb.db` (MusicBrainz build) or the legacy `data/collaboration_network.db`. Rebuild with the steps under *Rebuilding the Network*, or set `RABBITHOLE_DB` to a valid path.

### No preview player shown for a song
- Expected when the connecting song has no acceptable Spotify match — the app degrades gracefully to the song title with no player, rather than guess and risk playing the wrong song.

### "No connection found"
- Expected for artists genuinely disconnected from Kendrick within the graph (different eras/genres). Note MusicBrainz uses canonical artist names (e.g. "Ye", not "Kanye West"), so search by the canonical name.

### A connection routes through an unexpected/unofficial-looking song
- MusicBrainz occasionally credits a bootleg or mashup recording as a genuine collaboration (e.g. a Beatles→Kendrick edge through an unofficial mashup). This is a known, accepted gap — see `docs/RUNBOOK.md`'s "Known accepted gaps."

### Module not found / import errors
- Make sure you're running Python commands from the repo root (`src/` is added to the path relative to it)
- Reinstall dependencies: `pip install -r requirements.txt`, `npm install` in `frontend/`, and `npm install` in `worker/`

## Project Structure

```
six-degrees-kdot/
├── worker/                         # Cloudflare Worker (production API)
│   ├── src/index.ts                #   search / connection / resolve-track
│   └── wrangler.jsonc               #   D1 binding + deploy config
├── frontend/                       # Next.js app (Vercel) + /demo static route
├── api/
│   └── main.py                     # FastAPI engine — local dev/validation only
├── requirements.txt
├── src/
│   ├── musicbrainz_ingest.py       # MusicBrainz dump -> master graph
│   ├── path_tree.py                # Precomputed shortest-path tree from Kendrick
│   ├── photo_prebake.py            # Offline artist-photo enrichment
│   ├── track_prebake.py            # Offline Spotify track-ID enrichment
│   ├── preview_fetcher.py          # iTunes + Deezer (dev-only fallback path)
│   ├── spotify_preview.py          # Scraped-embed preview resolver (dev-only, see docstring)
│   ├── database.py                  # SQLite schema/query layer
│   ├── path_finder_sqlite.py       # Live BFS — the path_tree.py validation oracle
│   ├── build_network_sqlite.py     # Legacy Spotify crawler (retained fallback)
│   └── data_fetcher.py             # Legacy Spotify API client (retained fallback)
├── scripts/
│   ├── export_serving_db.py        # Master DB -> D1 serving DB + FTS5 setup
│   ├── export_demo.py              # Master DB -> static /demo JSON
│   ├── showcase_artists.json       # /demo's curated artist list (name+id)
│   ├── fetch_musicbrainz_dump.sh   # Download + stage the MB core-dump subset
│   ├── verify_coverage.py          # Coverage/degree-distribution report
│   └── debug_albums.py             # Dev utility
├── data/
│   ├── collaboration_network_mb.db # Master graph (build source of truth; gitignored)
│   └── mb_raw/                      # Staged MB dump tables (gitignored)
├── sessions/                        # Dated work-session logs
└── docs/
    ├── RUNBOOK.md                  # Full build/deploy pipeline
    ├── ROADMAP.md                  # Scoped near-term feature roadmap
    └── archive/                    # Original SI 507 course artifacts
```

## Data Sources

| Data Source | URL | Description |
|-------------|-----|-------------|
| MusicBrainz core dump | https://musicbrainz.org/doc/MusicBrainz_Database/Download | CC0 collaboration graph source (artists, recordings, artist credits, releases) — built locally, no rate limit |
| Wikidata / Wikimedia Commons | https://query.wikidata.org | Artist photos, offline pre-bake (primary) |
| TheAudioDB | https://www.theaudiodb.com | Artist photos, offline pre-bake (secondary) |
| Deezer API | https://developers.deezer.com | Artist photos, offline pre-bake (tertiary) |
| Spotify Web API | https://developer.spotify.com/documentation/web-api | Official track-ID resolution (offline pre-bake + the Worker's lazy resolve) and the embed player — never scraped |

**Authentication**: MusicBrainz data is CC0, no auth. Spotify requires official client-credentials (used only for track-ID *resolution*, never for fetching audio — previews render via Spotify's own embed iframe, client-side). Photo sources are free/no-auth.

## What's Next

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the current, intentionally short list of planned next features.
