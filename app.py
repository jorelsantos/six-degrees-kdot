"""
Six Degrees of Kendrick Lamar - Streamlit Web App

Find the shortest collaboration path between any artist and Kendrick Lamar.
"""

import os
import streamlit as st
from pathlib import Path
from urllib.parse import quote_plus
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from database import CollaborationDatabase, disambiguate_labels
from path_finder_sqlite import PathFinder
from preview_fetcher import get_preview


# --- Reversible data-source config (U5) ------------------------------------
# The app selects its graph DB via a single config point so cutover between the
# MusicBrainz build and the retained Spotify build is a one-line/env change.
#   RABBITHOLE_DB   -> explicit DB path (highest precedence)
# Otherwise: prefer the MusicBrainz DB if built, else fall back to the Spotify DB.
_DATA_DIR = Path(__file__).parent / "data"
MB_DB_PATH = _DATA_DIR / "collaboration_network_mb.db"
SPOTIFY_DB_PATH = _DATA_DIR / "collaboration_network.db"


def resolve_db_path() -> Path:
    env = os.environ.get("RABBITHOLE_DB")
    if env:
        return Path(env)
    if MB_DB_PATH.exists():
        return MB_DB_PATH
    return SPOTIFY_DB_PATH


# Page configuration
st.set_page_config(
    page_title="Six Degrees of Kendrick Lamar",
    page_icon="🎤",
    layout="centered"
)


@st.cache_resource
def load_database():
    """Load the database (cached to avoid reloading on every interaction)."""
    db_path = resolve_db_path()
    if not db_path.exists():
        return None
    return CollaborationDatabase(str(db_path))


@st.cache_resource
def load_path_finder(_db):
    """Load the path finder (cached)."""
    return PathFinder(_db)


@st.cache_resource
def resolve_kendrick_id(_db) -> str:
    """
    Resolve Kendrick's node id from the active DB rather than hardcoding a
    provider-specific id — the Spotify DB keys on a Spotify id, the MusicBrainz
    DB keys on an MBID. An explicit RABBITHOLE_KENDRICK_ID overrides.
    """
    env = os.environ.get("RABBITHOLE_KENDRICK_ID")
    if env:
        return env
    artist = _db.get_artist_by_name("Kendrick Lamar")
    return artist["id"] if artist else ""


def display_artist_card(artist_name: str, artist_id: str):
    """Display a compact artist card - clean, modern, professional."""
    st.markdown(f"""
        <div style="
            background: #181818;
            border-radius: 10px;
            padding: 16px 20px;
            margin: 12px auto;
            max-width: 340px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            border: 1px solid #1DB954;
        ">
            <div style="
                font-size: 1.35rem;
                font-weight: 800;
                color: #FFFFFF;
                letter-spacing: -0.01em;
                margin-bottom: 6px;
            ">
                {artist_name}
            </div>
            <div style="
                width: 32px;
                height: 2px;
                background: #1DB954;
                margin: 0 auto;
                border-radius: 2px;
            "></div>
        </div>
    """, unsafe_allow_html=True)


def display_path(connection: dict):
    """Display the connection path with artist cards and songs."""
    degrees = connection['degrees']

    # Degrees header - compact, no emoji (professional).
    if degrees == 0:
        st.markdown("""
            <div style="
                text-align: center;
                padding: 14px 20px;
                background: linear-gradient(135deg, rgba(29, 185, 84, 0.18), rgba(29, 185, 84, 0.04));
                border-radius: 10px;
                border: 1px solid #1DB954;
                margin-bottom: 20px;
            ">
                <div style="font-size: 1.1rem; font-weight: 700; color: #1DB954;">
                    That's Kendrick Lamar himself
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        label = "Degree" if degrees == 1 else "Degrees"
        st.markdown(f"""
            <div style="
                text-align: center;
                padding: 14px 20px;
                background: linear-gradient(135deg, rgba(29, 185, 84, 0.18), rgba(29, 185, 84, 0.04));
                border-radius: 10px;
                border: 1px solid #1DB954;
                margin-bottom: 20px;
            ">
                <span style="font-size: 1.6rem; font-weight: 900; color: #FFFFFF; vertical-align: middle;">
                    {degrees}
                </span>
                <span style="font-size: 0.95rem; color: #B3B3B3; margin-left: 8px; vertical-align: middle;">
                    {label} of separation
                </span>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("")

    # Path visualization with cards
    path_artists = connection['path']
    connections = connection['connections']

    for i, artist in enumerate(path_artists):
        # Display artist card
        display_artist_card(artist['name'], artist['id'])

        # If not the last artist, show the connecting songs
        if i < len(path_artists) - 1:
            # Find the connection between this artist and the next
            conn = connections[i]
            songs = conn['songs']
            # Per-song full lineup (falls back to bare names for the legacy DB).
            song_details = conn.get('song_details') or [
                {'name': s, 'collaborators': []} for s in songs
            ]
            from_artist = conn['from']['name']
            to_artist = conn['to']['name']

            # Build the whole "Collaborated On" section as ONE self-contained
            # HTML string. Streamlit's current markdown renderer escapes HTML
            # blocks left with unclosed tags across separate st.markdown calls,
            # so every tag opened here is also closed here.
            song_rows = ""
            for detail in song_details[:3]:
                song = detail['name']
                # Other artists on the track beyond the two path endpoints —
                # the delightful "who else is on this?" detail.
                endpoints = {from_artist.lower(), to_artist.lower()}
                others = [c for c in detail.get('collaborators', []) if c.lower() not in endpoints]
                feat_html = ""
                if others:
                    shown = ", ".join(others[:6]) + ("…" if len(others) > 6 else "")
                    feat_html = (
                        f'<div style="color:#B3B3B3;font-size:0.8rem;margin:2px 0 4px 24px;">'
                        f'with {shown}</div>'
                    )

                # Free, no-auth 30s preview (iTunes primary, Deezer fallback);
                # degrades gracefully to no player when none is found.
                preview = get_preview(song, [from_artist, to_artist])

                audio_html = ""
                if preview:
                    audio_html = (
                        f'<audio controls style="width:100%;height:32px;margin-top:8px;">'
                        f'<source src="{preview.preview_url}" type="audio/mpeg">'
                        f'</audio>'
                    )

                # Store link-out proximate to the preview (honors iTunes terms;
                # aligns with STRATEGY.md's "link out to verify" behavior).
                if preview and preview.store_url:
                    label = "Listen on Apple Music" if preview.provider == "itunes" else "Listen on Deezer"
                    link = preview.store_url
                else:
                    label = "Search on Apple Music"
                    link = f"https://music.apple.com/us/search?term={quote_plus(song + ' ' + from_artist)}"
                link_html = (
                    f'<a href="{link}" target="_blank" style="display:inline-block;'
                    f'margin-top:8px;font-size:0.8rem;color:#1DB954;text-decoration:none;">'
                    f'&#9654; {label}</a>'
                )

                song_rows += (
                    f'<div style="padding:12px 0;border-bottom:1px solid #282828;">'
                    f'<div style="display:flex;align-items:center;margin-bottom:4px;">'
                    f'<span style="color:#1DB954;font-weight:700;margin-right:12px;font-size:1.1rem;">&#9834;</span>'
                    f'<span style="color:#FFFFFF;font-weight:500;font-size:1rem;">{song}</span>'
                    f'</div>{feat_html}{audio_html}{link_html}</div>'
                )

            more_html = ""
            if len(songs) > 3:
                n = len(songs) - 3
                more_html = (
                    f'<div style="text-align:center;color:#B3B3B3;font-size:0.875rem;'
                    f'margin-top:16px;font-style:italic;">+{n} more collaboration'
                    f'{"s" if n > 1 else ""}</div>'
                )

            # Header names the pair this connection is between (Q1: pair label),
            # so it's clear whose collaboration these songs are.
            st.markdown(
                '<div style="margin:20px auto;max-width:600px;">'
                '<div style="text-align:center;margin-bottom:14px;">'
                '<div style="display:inline-block;font-size:0.75rem;font-weight:700;'
                'text-transform:uppercase;letter-spacing:0.1em;color:#1DB954;'
                'background:rgba(29,185,84,0.1);padding:5px 16px;border-radius:500px;'
                'border:1px solid #1DB954;">Collaborated On</div>'
                f'<div style="color:#B3B3B3;font-size:0.9rem;margin-top:8px;">'
                f'{from_artist} &times; {to_artist}</div></div>'
                '<div style="background:#181818;border-radius:10px;padding:16px;'
                'box-shadow:0 4px 12px rgba(0,0,0,0.4);">'
                f'{song_rows}{more_html}'
                '</div></div>',
                unsafe_allow_html=True,
            )


def main():
    # Custom CSS for Spotify aesthetic
    st.markdown("""
        <style>
        /* Spotify color variables */
        :root {
            --spotify-green: #1DB954;
            --spotify-black: #121212;
            --spotify-card: #181818;
            --spotify-gray: #B3B3B3;
            --spotify-white: #FFFFFF;
        }

        /* Main title styling */
        h1 {
            font-weight: 900;
            letter-spacing: -0.02em;
            margin-bottom: 0.5rem;
        }

        /* Clean input styling */
        .stTextInput input {
            border-radius: 8px;
            font-size: 1.1rem;
            padding: 0.75rem;
            background-color: #181818;
            border: 1px solid #282828;
        }

        /* Button styling - Spotify style */
        .stButton button {
            border-radius: 500px;
            font-weight: 700;
            padding: 0.75rem 2rem;
            transition: all 0.2s;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-size: 0.875rem;
        }

        .stButton button:hover {
            transform: scale(1.04);
        }

        /* Spotify aesthetic accents */
        .stMarkdown {
            line-height: 1.6;
        }

        /* Clean card styling */
        .element-container {
            margin-bottom: 1rem;
        }

        /* Audio player styling */
        audio {
            filter: brightness(0.9) contrast(1.1);
            border-radius: 8px;
        }

        audio::-webkit-media-controls-panel {
            background-color: #282828;
        }

        audio::-webkit-media-controls-play-button {
            background-color: #1DB954;
            border-radius: 50%;
        }

        /* Success message styling */
        .stAlert {
            border-radius: 8px;
        }

        /* Divider styling */
        hr {
            border: none;
            height: 1px;
            background: linear-gradient(90deg, transparent, #1DB954, transparent);
            margin: 2rem 0;
        }
        </style>
    """, unsafe_allow_html=True)

    # Title
    st.title("Six Degrees of Kendrick Lamar")
    st.markdown("*Find the collaboration path between any artist and Kendrick Lamar*")
    st.markdown("")

    # Load database
    db = load_database()

    if db is None:
        st.error("Database not found. Please run the network builder first.")
        st.code("python3 src/build_network_musicbrainz.py", language="bash")
        return

    # Resolve Kendrick's node id from whichever DB is active (MBID or Spotify id).
    kendrick_id = resolve_kendrick_id(db)

    # Search input with autocomplete
    artist_name = st.text_input(
        "Search an artist",
        placeholder="e.g. Drake, SZA, Sinatra…",
        key="artist_search"
    )

    # Suggestions and submit share ONE resolution pipeline (resolve_artist) —
    # plan 2026-07-06-002 KTD1. Suggestion clicks pin the exact node by id;
    # the submit button auto-runs the same list's head.
    selected_artist = None
    candidates = []
    if artist_name and len(artist_name) >= 2:
        candidates = db.resolve_artist(artist_name, limit=8)

        if candidates:
            st.markdown("**Suggestions:**")
            # Single column, ranked order — the top hit stays visually first.
            # Duplicate names carry a collab-count qualifier so three
            # "The Game" buttons are tellable-apart (R6).
            labels = disambiguate_labels(candidates)
            for suggestion, label in zip(candidates, labels):
                if st.button(
                    label,
                    key=f"suggestion_{suggestion['id']}",
                    use_container_width=True
                ):
                    selected_artist = suggestion

    st.markdown("")

    # Search button
    search_clicked = st.button("Find Connection", type="primary", use_container_width=True)

    if search_clicked or selected_artist:
        # Determine which artist to search for
        if selected_artist:
            artist = selected_artist
        elif artist_name:
            with st.spinner(f"Searching for {artist_name}..."):
                # Submit auto-runs the top-ranked candidate (R2): typos,
                # accents, punctuation, and partial names resolve instead of
                # dead-ending. The honest "isn't in our network" only fires
                # when nothing plausible matches (gibberish).
                submit_candidates = candidates or db.resolve_artist(artist_name, limit=8)
                if not submit_candidates:
                    st.error(f"'{artist_name}' isn't in our network yet.")
                    st.info("Try a different spelling or another artist.")
                    return
                artist = submit_candidates[0]
                if artist['name'].strip().lower() != artist_name.strip().lower():
                    # Same-render notice: it lives and dies with this result —
                    # no session_state — matching every other message here.
                    st.markdown(
                        f'<div style="text-align:center;color:#B3B3B3;'
                        f'font-size:0.9rem;margin:4px 0 12px 0;">'
                        f'Showing results for <span style="color:#1DB954;'
                        f'font-weight:700;">{artist["name"]}</span>'
                        f' — not who you meant? Pick from the suggestions above.</div>',
                        unsafe_allow_html=True,
                    )
        else:
            st.warning("Please enter an artist name.")
            return

        with st.spinner(f"Finding connection to Kendrick..."):
            # Check if it's Kendrick himself
            if artist['id'] == kendrick_id:
                st.balloons()
                st.success("🎤 That's Kendrick Lamar himself! 0 degrees of separation!")
                return

            # Find path
            path_finder = load_path_finder(db)
            connection = path_finder.find_connection(artist['id'], kendrick_id)

            if connection:
                display_path(connection)
            else:
                st.error("No connection found.")
                st.markdown(f"*{artist['name']} doesn't have a path to Kendrick Lamar in the current network.*")

    # Attribution footer (MusicBrainz data license good-citizenship; Apple/iTunes
    # store-link terms). Rendered on every view.
    st.markdown("""
        <div style="
            margin-top: 48px;
            padding-top: 16px;
            border-top: 1px solid #282828;
            text-align: center;
            color: #808080;
            font-size: 0.75rem;
            line-height: 1.6;
        ">
            Collaboration data from
            <a href="https://musicbrainz.org" target="_blank" style="color:#1DB954;text-decoration:none;">MusicBrainz</a>
            (CC0). Song previews and links via the
            <a href="https://www.apple.com/apple-music/" target="_blank" style="color:#1DB954;text-decoration:none;">Apple Music / iTunes</a>
            and <a href="https://www.deezer.com" target="_blank" style="color:#1DB954;text-decoration:none;">Deezer</a>
            APIs. Not affiliated with Apple, Deezer, or the artists.
        </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
