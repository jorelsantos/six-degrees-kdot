================================================================================
Six Degrees of Kendrick Lamar: Music Collaboration Network Analyzer
================================================================================

PROJECT OVERVIEW
================================================================================
An interactive CLI application that finds the shortest path between any artist
and Kendrick Lamar, showing their degrees of separation and the specific songs
that connect them. Built with Python, NetworkX, and the Spotify API.

Inspired by "Six Degrees of Kevin Bacon," this project explores how artists in
hip-hop and music are connected through their collaborations.


HOW IT WORKS
================================================================================
1. Enter any artist name (e.g., "Drake", "SZA", "Taylor Swift")
2. Get instant results showing:
   - Degrees of separation from Kendrick Lamar
   - The connection path (Artist A -> Artist B -> Kendrick)
   - Specific songs they collaborated on at each step


QUICK START (TL;DR)
================================================================================

# 1. Install (~1 minute)
git clone https://github.com/jorelsantos-um/six-degrees-kdot.git
cd six-degrees-kdot
pip install -r requirements.txt

# 2. Get Spotify credentials (~2-3 minutes)
# Visit https://developer.spotify.com/dashboard
# Create app, copy Client ID and Client Secret

# 3. Create .env file
cp .env.example .env
# Edit .env with your credentials

# 4. Build network (10-15 minutes - ONLY FIRST TIME!)
python3 src/network_builder.py

# 5. Run!
python3 main.py

Total setup time: ~15-20 minutes (mostly waiting for network to build)


FEATURES
================================================================================

Shortest Path Finding
- Uses breadth-first search to find the shortest connection between any two artists
- Shows exact collaboration songs at each step in the path
- Handles artists not in the network by dynamically expanding it

Smart Network Building
- Pre-builds a 2-degree collaboration network from Kendrick Lamar
- Analyzes artists' albums to discover collaborations
- Caches data to minimize API calls and improve performance
- Automatically expands when searching for new artists

Data Quality
- Includes both primary albums and guest features
- Smart track filtering for guest appearances
- Prioritizes studio albums over singles
- Eliminates duplicate collaborators (case-insensitive)
- Validates and caches all Spotify API responses


NETWORK REPRESENTATION
================================================================================
Nodes: Artists with metadata (name, ID, popularity, genres)
Edges: Collaborations between artists
Edge Attributes: List of songs they collaborated on


DATA SOURCES
================================================================================
This project uses data from the Spotify Web API to collect information about
artists, albums, tracks, and collaborations.

Data Source: Spotify Web API
URL: https://developer.spotify.com/documentation/web-api
Description: Official Spotify REST API providing access to music catalog data
             including artists, albums, tracks, and audio features

Authentication: OAuth 2.0 Client Credentials flow
Base URL: https://api.spotify.com/v1/


DATA ACCESS TECHNIQUES
================================================================================
This project uses the following techniques to access and manage data:

1. OAuth 2.0 Authentication
   - Client Credentials flow for application-level access
   - Access tokens are automatically refreshed when expired
   - Credentials stored securely in .env file (not committed to git)

2. REST API Calls
   - HTTP GET requests to Spotify Web API endpoints
   - Endpoints used:
     * /v1/search - Search for artists by name
     * /v1/artists/{id} - Get artist metadata
     * /v1/artists/{id}/albums - Get artist's discography
     * /v1/albums/{id}/tracks - Get tracks from an album
   - JSON response parsing for all data
   - Error handling with retry logic for rate limits

3. Caching Strategy
   - All API responses cached as JSON files in data/ directory
   - Cache key: MD5 hash of the API endpoint URL
   - Cache expiration: 7 days (604800 seconds)
   - Cache hit avoids unnecessary API calls, improving performance
   - Cache miss triggers new API request and updates cache file
   - Example: get_artist_albums() checks cache before calling API

4. Data Persistence
   - Network graph saved as pickle file (collaboration_network.pkl)
   - Allows instant loading without rebuilding 10-15 minute network
   - Graph contains all nodes, edges, and attributes in NetworkX format


DATA SUMMARY
================================================================================
The application stores and processes the following data structures:

Artist Data (Nodes in Network Graph)
------------------------------------
- id: Spotify unique artist identifier (string)
- name: Artist display name (string)
- popularity: Spotify popularity score 0-100 (integer)
- genres: List of associated genres (list of strings)
- followers: Total follower count (integer, optional)

Album Data (Used for Collaboration Discovery)
----------------------------------------------
- id: Spotify unique album identifier (string)
- name: Album title (string)
- release_date: Album release date (string, YYYY-MM-DD)
- album_type: Type of release - "album", "single", or "compilation" (string)
- total_tracks: Number of tracks on album (integer)
- is_primary_artist: Whether artist is primary owner vs. guest (boolean)

Track Data (Used to Identify Collaborations)
---------------------------------------------
- id: Spotify unique track identifier (string)
- name: Track title (string)
- artists: List of all artists credited on track (list of artist objects)
- duration_ms: Track length in milliseconds (integer)
- track_number: Position on album (integer)

Collaboration Data (Edges in Network Graph)
-------------------------------------------
- source_artist: Starting artist node ID (string)
- target_artist: Ending artist node ID (string)
- songs: List of track names they collaborated on (list of strings)
- weight: Number of collaborations (integer, implicit from songs list length)

Network Graph Statistics
------------------------
- total_artists: Total number of artist nodes in graph (integer)
- total_collaborations: Total number of collaboration edges (integer)
- average_collaborators: Mean number of collaborators per artist (float)
- degrees_from_kendrick: Maximum path length in network (integer)


REQUIREMENTS
================================================================================
- Python 3.7+
- Spotify API credentials (free)
- Dependencies: networkx, requests, python-dotenv


GETTING STARTED
================================================================================

1. Clone and Install (~1 minute)
---------------------------------
git clone https://github.com/jorelsantos-um/six-degrees-kdot.git
cd six-degrees-kdot
pip install -r requirements.txt  # Installs networkx, requests, python-dotenv


2. Get Spotify API Credentials (~2-3 minutes)
----------------------------------------------
1. Go to https://developer.spotify.com/dashboard
2. Log in with your Spotify account (create one if needed)
3. Click "Create App"
4. Fill in:
   - App name: "Six Degrees of Kendrick Lamar" (or any name)
   - App description: "SI 507 Final Project"
   - Redirect URI: http://localhost
5. Click "Create"
6. Copy your Client ID and Client Secret (click "Show Client Secret")


3. Create .env File
-------------------
cp .env.example .env
# Edit .env with your actual credentials:
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here


4. Build the Network (~10-15 minutes - FIRST TIME ONLY)
--------------------------------------------------------
python3 src/network_builder.py

IMPORTANT: This step takes 10-15 minutes! The app makes many API calls to
build a 2-degree collaboration network from Kendrick Lamar. This is NORMAL
and only needs to be done once. The network is saved and reused for all
future searches.


5. Run the Application (Instant if network already built)
----------------------------------------------------------
python3 main.py

Once the network is built, the app starts instantly and searches are nearly
immediate!


USAGE
================================================================================

Example 1: Direct Collaboration (1 Degree)
-------------------------------------------
Enter artist name (or 'quit' to exit): Drake
Found: Drake

1 degree of separation

PATH:
Drake -> Kendrick Lamar

CONNECTIONS:
1. Drake & Kendrick Lamar
   - Poetic Justice
   - Buried Alive Interlude
   ... and 1 more

Enter artist name (or 'quit' to exit):


Example 2: Two Degrees of Separation
-------------------------------------
Enter artist name (or 'quit' to exit): Travis Scott
Found: Travis Scott

2 degrees of separation

PATH:
Travis Scott -> SZA -> Kendrick Lamar

CONNECTIONS:
1. Travis Scott & SZA
   - Love Galore

2. SZA & Kendrick Lamar
   - All The Stars
   - Doves in the Wind
   ... and 1 more

Enter artist name (or 'quit' to exit):


Example 3: No Connection Found
-------------------------------
Enter artist name (or 'quit' to exit): Frank Sinatra
Found: Frank Sinatra
No path that we know of.


Type 'quit' or 'exit' to leave the application.


TROUBLESHOOTING
================================================================================

"Authentication error" / "Could not connect to Spotify API"
------------------------------------------------------------
Problem: Spotify API credentials are missing or invalid

Solutions:
1. Check that .env file exists in the project root directory
2. Verify credentials are correct (no extra spaces, quotes, or line breaks)
3. Make sure you copied BOTH SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
4. Try regenerating credentials in the Spotify Developer Dashboard
5. Ensure your Spotify app is not in restricted/quota exceeded mode


"No saved network found" message
---------------------------------
Problem: Network hasn't been built yet

Solutions:
- Run "python3 src/network_builder.py" first (takes 10-15 minutes)
- Or type "yes" when the app prompts you to build the network
- Check that data/collaboration_network.pkl file exists after building


Network building takes too long / times out / fails
----------------------------------------------------
Problem: Slow internet, API rate limiting, or connection issues

Solutions:
- Ensure you have a stable internet connection
- Wait a few minutes if you hit rate limits - the app will retry automatically
- If it fails partway through, you can restart - cached data is preserved
- Network building progress is saved in data/ folder as JSON files


"Could not find artist" / "Could not find '[artist name]'"
-----------------------------------------------------------
Problem: Artist name spelling, artist not on Spotify, or search issue

Solutions:
- Check spelling carefully (try the artist's full legal name)
- Try alternate spellings or stage names
- Verify the artist exists on Spotify by searching there first
- Some very obscure artists may not be in Spotify's database


"No path that we know of"
--------------------------
Problem: Artist genuinely not connected to Kendrick within the network

Solutions:
- This is EXPECTED BEHAVIOR for artists from very different eras or genres
- Example: Frank Sinatra (died 1998) has no connection to Kendrick
- Example: Classical composers or artists from completely different musical universes
- The app will attempt 2-degree network expansion, but some artists truly aren't connected
- This is a feature, not a bug - it correctly identifies when no path exists


Python version errors / "SyntaxError" / Module not found
---------------------------------------------------------
Problem: Using incompatible Python version or missing dependencies

Solutions:
- Ensure Python 3.7 or higher is installed: python3 --version
- Use "python3" command instead of "python"
- Reinstall dependencies: pip install -r requirements.txt
- On some systems, use "pip3" instead of "pip"


"Permission denied" or file access errors
------------------------------------------
Problem: Insufficient permissions to create files in data/ directory

Solutions:
- Make sure you have write permissions in the project directory
- Try running from your home directory or a location you own
- Check that data/ folder exists and is writable


PROJECT STRUCTURE
================================================================================
six-degrees-kdot/
├── main.py                          # Main interactive application
├── src/
│   ├── data_fetcher.py             # Spotify API client & caching
│   ├── network_builder.py          # Graph building with NetworkX
│   └── path_finder.py              # Shortest path algorithms
├── data/
│   ├── collaboration_network.pkl   # Saved network graph
│   └── *.json                      # Cached API responses
├── requirements.txt                # Python dependencies
├── README.md                       # GitHub-formatted documentation
└── README.txt                      # This file (plain text)


COURSE INFORMATION
================================================================================
SI 507 Final Project
University of Michigan School of Information
