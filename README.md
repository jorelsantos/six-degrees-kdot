# Six Degrees of Kendrick Lamar

A Streamlit web app that finds the shortest collaboration path between any artist and Kendrick Lamar — degrees of separation, the connecting path, and the specific songs at each step. Built with Python and SQLite; the collaboration graph is built from the **MusicBrainz** database dump (CC0), and 30-second song previews come from the free **iTunes Search API** (with a **Deezer** fallback). Styled after the Spotify UI.

> **Data sources (2026-07):** the graph was migrated from a Spotify crawl to a MusicBrainz-dump build (no API rate limits, complete data), and previews moved off Spotify's deprecated `preview_url` to iTunes/Deezer. **No Spotify credentials are required.** Every edge is a *shared recording* co-crediting two artists — that recording is the connecting song. Details: [`docs/plans/2026-07-04-001-feat-musicbrainz-graph-migration-plan.md`](docs/plans/2026-07-04-001-feat-musicbrainz-graph-migration-plan.md). The Spotify crawler is retained as a fallback but is no longer the primary path.

Inspired by "Six Degrees of Kevin Bacon," this project explores how artists in hip-hop and music are connected through their collaborations.

> **Project history:** this started as a University of Michigan SI 507 course final project (a terminal CLI app). The original course writeup is archived at [`docs/archive/`](docs/archive/). The app has since been rebuilt as a Streamlit web app on a SQLite-backed graph — this README reflects the current app, not the original CLI.

## How It Works

1. **Enter any artist name** (e.g., "Drake", "SZA", "Taylor Swift")
2. **Get instant results** showing:
   - Degrees of separation from Kendrick Lamar
   - The connection path (Artist A → Artist B → Kendrick)
   - The specific songs they collaborated on at each step, with a 30-second preview (iTunes/Deezer) and a "Listen on Apple Music" link where available

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/jorelsantos-um/six-degrees-kdot.git
cd six-degrees-kdot
pip install -r requirements.txt

# 2. Run the app — no API credentials needed
streamlit run app.py
```

No Spotify (or any) API key is required: the graph is pre-built into SQLite, and previews are fetched at query time from the free, no-auth iTunes/Deezer APIs. By default the app loads the MusicBrainz-built graph (`data/collaboration_network_mb.db`) if present, otherwise the retained Spotify-built graph. Override with the `RABBITHOLE_DB` env var.

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
- Breadth-first search over the collaboration graph to find the shortest connection between any two artists
- Shows exact collaboration songs at each step, with inline Spotify audio previews
- Falls back to live Spotify search for artists not yet in the pre-built network

### Data Quality
- Includes both primary albums and guest features
- Smart track filtering for guest appearances
- Prioritizes studio albums over singles
- Deduplicates collaborators case-insensitively and dedups recording versions to a canonical connecting song
- Edges restricted to shared recordings on **Official** releases (excludes bootleg/mashup, interview/spokenword, and DJ-mix blends)

## Architecture

- **`app.py`** — Streamlit web app (entry point). Loads the SQLite database, runs path lookups, and renders the Spotify-styled UI.
- **`src/database.py`** — SQLite schema and query layer for the collaboration graph.
- **`src/path_finder_sqlite.py`** — BFS shortest-path logic over the SQLite-backed graph.
- **`src/musicbrainz_ingest.py`** — Builds the collaboration graph from the staged MusicBrainz dump (Official-release filter + co-credit edges) into `data/collaboration_network_mb.db`. **Primary build path.**
- **`src/preview_fetcher.py`** — Query-time 30s previews from iTunes (primary) + Deezer (fallback), with a store link-out.
- **`scripts/fetch_musicbrainz_dump.sh`** — Downloads + stages the MusicBrainz core-dump table subset.
- **`src/build_network_sqlite.py`**, **`src/data_fetcher.py`** — Legacy Spotify crawler + API client. Retained as a fallback; no longer primary.
- **`scripts/debug_albums.py`** — Standalone dev utility for inspecting which albums/tracks are being analyzed for a given artist.

### Data Model
- **Nodes**: Artists keyed on **MusicBrainz ID (MBID)**, with a display name (Spotify IDs in the legacy DB)
- **Edges**: Collaborations between artists
- **Edge Attributes**: Songs they collaborated on

## Requirements

- Python 3.7+
- No API credentials required (the graph is pre-built; previews use free, no-auth iTunes/Deezer)
- Dependencies: `requests`, `python-dotenv`, `streamlit` (see `requirements.txt`)

## Troubleshooting

### "Database not found"
- The app expects `data/collaboration_network_mb.db` (MusicBrainz build) or the legacy `data/collaboration_network.db`. Rebuild with the steps under *Rebuilding the Network*, or set `RABBITHOLE_DB` to a valid path.

### No preview player shown for a song
- Expected when neither iTunes nor Deezer has a match for that title/artist — the app degrades gracefully to the song title + a store link, with no broken player.

### "No connection found"
- Expected for artists genuinely disconnected from Kendrick within the depth-2 graph (different eras/genres). Note MusicBrainz uses canonical artist names (e.g. "Ye", not "Kanye West"), so search by the canonical name.

### Module not found / import errors
- Make sure you're running `streamlit run app.py` from the repo root
- Reinstall dependencies: `pip install -r requirements.txt`

## Project Structure

```
six-degrees-kdot/
├── app.py                          # Streamlit app (entry point)
├── requirements.txt
├── src/
│   ├── musicbrainz_ingest.py       # MusicBrainz dump -> graph (primary builder)
│   ├── preview_fetcher.py          # iTunes + Deezer query-time previews
│   ├── database.py                 # SQLite schema/query layer
│   ├── path_finder_sqlite.py       # Shortest path (BFS) over SQLite graph
│   ├── build_network_sqlite.py     # Legacy Spotify crawler (retained fallback)
│   └── data_fetcher.py             # Legacy Spotify API client (retained fallback)
├── scripts/
│   ├── fetch_musicbrainz_dump.sh   # Download + stage the MB core-dump subset
│   ├── mb_spike.py                 # U8 validation spike (live-API proof of concept)
│   ├── verify_coverage.py          # Coverage/degree-distribution report
│   └── debug_albums.py             # Dev utility
├── data/
│   ├── collaboration_network_mb.db # MusicBrainz-built graph (default; gitignored)
│   ├── collaboration_network.db    # Legacy Spotify graph (retained fallback)
│   └── mb_raw/                      # Staged MB dump tables (gitignored)
├── sessions/                        # Dated work-session logs
└── docs/
    ├── ROADMAP.md                  # Scoped near-term feature roadmap
    └── archive/                    # Original SI 507 course artifacts
```

## Data Sources

| Data Source | URL | Description |
|-------------|-----|-------------|
| MusicBrainz core dump | https://musicbrainz.org/doc/MusicBrainz_Database/Download | CC0 collaboration graph source (artists, recordings, artist credits, releases) — built locally, no rate limit |
| iTunes Search API | https://performance-partners.apple.com/search-api | Free, no-auth 30-second song previews + Apple Music store links (primary) |
| Deezer API | https://developers.deezer.com | Free, no-auth 30-second preview fallback |
| Spotify Web API *(legacy)* | https://developer.spotify.com/documentation/web-api | Original crawl source, retained as a fallback; not the primary path |

**Authentication**: none required. MusicBrainz data is CC0; iTunes/Deezer previews are no-auth and fetched at query time (not cached/stored, per iTunes terms).

## What's Next

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the current, intentionally short list of planned next features.
