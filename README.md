# Six Degrees of Kendrick Lamar

A Streamlit web app that finds the shortest collaboration path between any artist and Kendrick Lamar — degrees of separation, the connecting path, and the specific songs at each step. Built with Python, SQLite, and the Spotify API, styled after the Spotify UI.

Inspired by "Six Degrees of Kevin Bacon," this project explores how artists in hip-hop and music are connected through their collaborations.

> **Project history:** this started as a University of Michigan SI 507 course final project (a terminal CLI app). The original course writeup is archived at [`docs/archive/`](docs/archive/). The app has since been rebuilt as a Streamlit web app on a SQLite-backed graph — this README reflects the current app, not the original CLI.

## How It Works

1. **Enter any artist name** (e.g., "Drake", "SZA", "Taylor Swift")
2. **Get instant results** showing:
   - Degrees of separation from Kendrick Lamar
   - The connection path (Artist A → Artist B → Kendrick)
   - The specific songs they collaborated on at each step, with Spotify preview playback where available

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/jorelsantos-um/six-degrees-kdot.git
cd six-degrees-kdot
pip install -r requirements.txt

# 2. Get Spotify API credentials
# Visit https://developer.spotify.com/dashboard, create an app,
# copy the Client ID and Client Secret

# 3. Create your .env file
cp .env.example .env
# Edit .env with your credentials

# 4. Run the app
streamlit run app.py
```

The repo ships with a pre-built `data/collaboration_network.db` (~27k artists), so the app works immediately after setup — no separate network-build step required for a fresh clone. Spotify credentials are still needed for live artist search and audio previews.

## Rebuilding the Network (Optional)

If you want to rebuild or expand the collaboration network from scratch:

```bash
python3 src/build_network_sqlite.py
```

This crawls outward from Kendrick Lamar via the Spotify API and repopulates `data/collaboration_network.db`. It uses parallel requests and rate limiting, but can still take a while depending on the configured depth — only needed if you want a fresh or deeper network than the one already in the repo.

## Features

### Shortest Path Finding
- Breadth-first search over the collaboration graph to find the shortest connection between any two artists
- Shows exact collaboration songs at each step, with inline Spotify audio previews
- Falls back to live Spotify search for artists not yet in the pre-built network

### Data Quality
- Includes both primary albums and guest features
- Smart track filtering for guest appearances
- Prioritizes studio albums over singles
- Deduplicates collaborators case-insensitively
- Caches all Spotify API responses locally to minimize repeat API calls

## Architecture

- **`app.py`** — Streamlit web app (entry point). Loads the SQLite database, runs path lookups, and renders the Spotify-styled UI.
- **`src/database.py`** — SQLite schema and query layer for the collaboration graph.
- **`src/path_finder_sqlite.py`** — BFS shortest-path logic over the SQLite-backed graph.
- **`src/build_network_sqlite.py`** — Crawls the Spotify API to build/expand `data/collaboration_network.db`.
- **`src/data_fetcher.py`** — Spotify API client, OAuth handling, and local JSON response caching.
- **`scripts/debug_albums.py`** — Standalone dev utility for inspecting which albums/tracks are being analyzed for a given artist.

### Data Model
- **Nodes**: Artists with metadata (name, Spotify ID, popularity, genres)
- **Edges**: Collaborations between artists
- **Edge Attributes**: Songs they collaborated on

## Requirements

- Python 3.7+
- Spotify API credentials (free)
- Dependencies: `requests`, `python-dotenv`, `streamlit` (see `requirements.txt`)

## Troubleshooting

### "Authentication error" / "Could not connect to Spotify API"
- Check that `.env` exists in the project root and both `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are set correctly (no extra spaces/quotes)
- Regenerate credentials in the Spotify Developer Dashboard if needed

### "No path that we know of"
- Expected for artists genuinely disconnected from Kendrick within the current network (different eras/genres), or for artists not yet in the pre-built network and not discoverable via live fallback lookup

### Module not found / import errors
- Make sure you're running `streamlit run app.py` from the repo root
- Reinstall dependencies: `pip install -r requirements.txt`

## Project Structure

```
six-degrees-kdot/
├── app.py                          # Streamlit app (entry point)
├── requirements.txt
├── src/
│   ├── data_fetcher.py             # Spotify API client & caching
│   ├── database.py                 # SQLite schema/query layer
│   ├── build_network_sqlite.py     # Network builder (Spotify API -> SQLite)
│   └── path_finder_sqlite.py       # Shortest path (BFS) over SQLite graph
├── scripts/
│   └── debug_albums.py             # Dev utility
├── data/
│   ├── collaboration_network.db    # Pre-built collaboration graph (tracked in git)
│   └── *.json                      # Cached Spotify API responses (gitignored)
├── sessions/                        # Dated work-session logs
└── docs/
    ├── ROADMAP.md                  # Scoped near-term feature roadmap
    └── archive/                    # Original SI 507 course artifacts
```

## Data Sources

| Data Source | URL | Description |
|-------------|-----|-------------|
| Spotify Web API | https://developer.spotify.com/documentation/web-api | Official Spotify REST API — artists, albums, tracks, and audio previews |

**Authentication**: OAuth 2.0 Client Credentials flow
**Caching**: API responses cached as JSON files in `data/`, keyed by MD5 hash of the endpoint URL, with a 7-day expiration

## What's Next

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the current, intentionally short list of planned next features.
