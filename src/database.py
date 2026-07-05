"""
SQLite Database Module for Six Degrees of Kendrick Lamar

This module handles all database operations for storing the artist
collaboration network in SQLite format for scalability and portability.
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager


class CollaborationDatabase:
    """
    Manages SQLite storage for the artist collaboration network.

    Tables:
        - artists: Artist nodes with metadata
        - collaborations: Edges between collaborating artists
        - songs: Song names for each collaboration
    """

    def __init__(self, db_path: str = "data/collaboration_network.db"):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_schema()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Artists table (nodes)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artists (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    popularity INTEGER DEFAULT 0,
                    genres TEXT DEFAULT '[]',
                    crawled INTEGER DEFAULT 0
                )
            """)

            # Migration guard: add `crawled` to databases created before this column existed.
            cursor.execute("PRAGMA table_info(artists)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            if "crawled" not in existing_columns:
                cursor.execute("ALTER TABLE artists ADD COLUMN crawled INTEGER DEFAULT 0")

            # Collaborations table (edges)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS collaborations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artist1_id TEXT NOT NULL,
                    artist2_id TEXT NOT NULL,
                    FOREIGN KEY (artist1_id) REFERENCES artists(id),
                    FOREIGN KEY (artist2_id) REFERENCES artists(id),
                    UNIQUE(artist1_id, artist2_id)
                )
            """)

            # Songs table (edge attributes). `collaborators` is a JSON array of
            # ALL artist names credited on the connecting recording (so the UI
            # can show the full lineup, e.g. "My Way" feat. Common & Lloyd).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collaboration_id INTEGER NOT NULL,
                    song_name TEXT NOT NULL,
                    collaborators TEXT DEFAULT '[]',
                    FOREIGN KEY (collaboration_id) REFERENCES collaborations(id)
                )
            """)

            # Migration guard: add `collaborators` to DBs created before it existed
            # (e.g. the legacy Spotify build), so both DBs load with one schema.
            cursor.execute("PRAGMA table_info(songs)")
            song_cols = {row[1] for row in cursor.fetchall()}
            if "collaborators" not in song_cols:
                cursor.execute("ALTER TABLE songs ADD COLUMN collaborators TEXT DEFAULT '[]'")

            # Artist aliases (alternate names -> canonical artist node). One row
            # per (artist, alias); lets a search for "Kanye West" resolve to the
            # canonical "Ye" node. Populated only by the MusicBrainz build; the
            # legacy Spotify DB simply has an empty table (CREATE IF NOT EXISTS),
            # so both DBs load under one schema and alias lookups no-op there.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artist_aliases (
                    artist_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    FOREIGN KEY (artist_id) REFERENCES artists(id),
                    UNIQUE(artist_id, alias)
                )
            """)

            # Indexes for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_collab_artist1
                ON collaborations(artist1_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_collab_artist2
                ON collaborations(artist2_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_songs_collab
                ON songs(collaboration_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_artist_name
                ON artists(name COLLATE NOCASE)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alias_name
                ON artist_aliases(alias COLLATE NOCASE)
            """)

    def add_artist(self, artist_id: str, name: str,
                   popularity: int = 0, genres: List[str] = None) -> None:
        """
        Add an artist to the database.

        Args:
            artist_id: Spotify artist ID
            name: Artist name
            popularity: Spotify popularity score (0-100)
            genres: List of genre strings
        """
        genres = genres or []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO artists (id, name, popularity, genres)
                VALUES (?, ?, ?, ?)
            """, (artist_id, name, popularity, json.dumps(genres)))

    def add_artist_alias(self, artist_id: str, alias: str) -> None:
        """
        Register an alternate name for an artist (so a search by that name
        resolves to this canonical node). Idempotent; skips aliases that are
        blank or identical to the canonical display name.

        Args:
            artist_id: Canonical artist id (MBID) the alias points to
            alias: The alternate name string
        """
        if not alias or not alias.strip():
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO artist_aliases (artist_id, alias)
                VALUES (?, ?)
            """, (artist_id, alias.strip()))

    def add_artist_aliases(self, artist_id: str, aliases: List[str]) -> None:
        """Bulk variant of add_artist_alias for one artist."""
        rows = [(artist_id, a.strip()) for a in (aliases or []) if a and a.strip()]
        if not rows:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR IGNORE INTO artist_aliases (artist_id, alias)
                VALUES (?, ?)
            """, rows)

    def mark_artist_crawled(self, artist_id: str) -> None:
        """
        Mark an artist as having had their own albums/collaborators crawled.

        This is the only reliable signal for resumability: the collaborations
        table stores undirected edges, so a crawled artist and one merely
        discovered as someone else's collaborator are otherwise indistinguishable.

        Args:
            artist_id: Spotify artist ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE artists SET crawled = 1 WHERE id = ?
            """, (artist_id,))

    def is_artist_crawled(self, artist_id: str) -> bool:
        """
        Check whether an artist has already been crawled (own albums processed).

        Args:
            artist_id: Spotify artist ID

        Returns:
            True if the artist exists and is marked crawled, False otherwise
            (including if the artist isn't in the database at all).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT crawled FROM artists WHERE id = ?", (artist_id,))
            row = cursor.fetchone()
            return bool(row and row["crawled"])

    def get_artist_neighbors(self, artist_id: str) -> List[str]:
        """
        Get an artist's collaborator IDs directly from stored edges, without
        a live API call. Used to resume a rebuild for artists already crawled.

        Args:
            artist_id: Spotify artist ID

        Returns:
            List of neighboring artist IDs (collaborators in either edge direction)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT artist1_id, artist2_id FROM collaborations
                WHERE artist1_id = ? OR artist2_id = ?
            """, (artist_id, artist_id))
            neighbors = []
            for row in cursor.fetchall():
                other = row["artist2_id"] if row["artist1_id"] == artist_id else row["artist1_id"]
                neighbors.append(other)
            return neighbors

    def add_collaboration(self, artist1_id: str, artist2_id: str,
                          song_name: str, collaborators: List[str] = None) -> None:
        """
        Add a collaboration between two artists.

        Args:
            artist1_id: First artist's ID (Spotify ID or MBID)
            artist2_id: Second artist's ID
            song_name: Name of the collaboration song
            collaborators: All artist names credited on the connecting recording
                (the full lineup, for display). Optional.
        """
        # Ensure consistent ordering for the unique constraint
        if artist1_id > artist2_id:
            artist1_id, artist2_id = artist2_id, artist1_id

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get or create collaboration
            cursor.execute("""
                INSERT OR IGNORE INTO collaborations (artist1_id, artist2_id)
                VALUES (?, ?)
            """, (artist1_id, artist2_id))

            # Get collaboration ID
            cursor.execute("""
                SELECT id FROM collaborations
                WHERE artist1_id = ? AND artist2_id = ?
            """, (artist1_id, artist2_id))
            collab_id = cursor.fetchone()['id']

            # Check if song already exists for this collaboration
            cursor.execute("""
                SELECT id FROM songs
                WHERE collaboration_id = ? AND song_name = ?
            """, (collab_id, song_name))

            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO songs (collaboration_id, song_name, collaborators)
                    VALUES (?, ?, ?)
                """, (collab_id, song_name, json.dumps(collaborators or [])))

    def get_artist(self, artist_id: str) -> Optional[Dict]:
        """
        Get artist by ID.

        Args:
            artist_id: Spotify artist ID

        Returns:
            Artist dict or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, popularity, genres
                FROM artists WHERE id = ?
            """, (artist_id,))
            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'name': row['name'],
                    'popularity': row['popularity'],
                    'genres': json.loads(row['genres'])
                }
            return None

    def get_artist_by_name(self, name: str) -> Optional[Dict]:
        """
        Get artist by name (case-insensitive).

        Args:
            name: Artist name to search

        Returns:
            Artist dict or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, popularity, genres
                FROM artists WHERE name = ? COLLATE NOCASE
            """, (name,))
            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'name': row['name'],
                    'popularity': row['popularity'],
                    'genres': json.loads(row['genres'])
                }

            # Fall back to an exact alias match (e.g. "Kanye West" -> "Ye"),
            # resolving to the canonical artist node. Prefer the more popular
            # artist when an alias is shared by several.
            cursor.execute("""
                SELECT a.id, a.name, a.popularity, a.genres
                FROM artist_aliases al
                JOIN artists a ON a.id = al.artist_id
                WHERE al.alias = ? COLLATE NOCASE
                ORDER BY a.popularity DESC
                LIMIT 1
            """, (name,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row['id'],
                    'name': row['name'],
                    'popularity': row['popularity'],
                    'genres': json.loads(row['genres'])
                }
            return None

    def search_artists(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search artists by name (partial match).

        Args:
            query: Search query
            limit: Maximum results to return

        Returns:
            List of matching artist dicts
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Match on the canonical name OR any alias, but return one row per
            # canonical artist (DISTINCT by id) so "Kanye" surfaces "Ye" once,
            # never a separate alias row. The alias join is a LEFT JOIN so the
            # legacy Spotify DB (no aliases) behaves exactly as before.
            like = f"%{query}%"
            cursor.execute("""
                SELECT a.id, a.name, a.popularity, a.genres
                FROM artists a
                LEFT JOIN artist_aliases al ON al.artist_id = a.id
                WHERE a.name LIKE ? COLLATE NOCASE
                   OR al.alias LIKE ? COLLATE NOCASE
                GROUP BY a.id
                ORDER BY a.popularity DESC, a.name
                LIMIT ?
            """, (like, like, limit))

            return [{
                'id': row['id'],
                'name': row['name'],
                'popularity': row['popularity'],
                'genres': json.loads(row['genres'])
            } for row in cursor.fetchall()]

    def artist_exists(self, artist_id: str) -> bool:
        """Check if artist is in database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM artists WHERE id = ?", (artist_id,))
            return cursor.fetchone() is not None

    def get_collaborators(self, artist_id: str) -> List[Dict]:
        """
        Get all collaborators for an artist.

        Args:
            artist_id: Spotify artist ID

        Returns:
            List of collaborator dicts with songs
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get collaborations where artist is either artist1 or artist2
            cursor.execute("""
                SELECT
                    CASE
                        WHEN c.artist1_id = ? THEN c.artist2_id
                        ELSE c.artist1_id
                    END as collaborator_id,
                    a.name as collaborator_name,
                    a.popularity,
                    c.id as collaboration_id
                FROM collaborations c
                JOIN artists a ON a.id = CASE
                    WHEN c.artist1_id = ? THEN c.artist2_id
                    ELSE c.artist1_id
                END
                WHERE c.artist1_id = ? OR c.artist2_id = ?
            """, (artist_id, artist_id, artist_id, artist_id))

            collaborators = []
            for row in cursor.fetchall():
                # Get songs for this collaboration
                cursor.execute("""
                    SELECT song_name FROM songs WHERE collaboration_id = ?
                """, (row['collaboration_id'],))
                songs = [s['song_name'] for s in cursor.fetchall()]

                collaborators.append({
                    'id': row['collaborator_id'],
                    'name': row['collaborator_name'],
                    'popularity': row['popularity'],
                    'songs': songs
                })

            return collaborators

    def get_collaboration_songs(self, artist1_id: str, artist2_id: str) -> List[str]:
        """
        Get songs two artists collaborated on.

        Args:
            artist1_id: First artist's Spotify ID
            artist2_id: Second artist's Spotify ID

        Returns:
            List of song names
        """
        # Ensure consistent ordering
        if artist1_id > artist2_id:
            artist1_id, artist2_id = artist2_id, artist1_id

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.song_name
                FROM songs s
                JOIN collaborations c ON s.collaboration_id = c.id
                WHERE c.artist1_id = ? AND c.artist2_id = ?
            """, (artist1_id, artist2_id))

            return [row['song_name'] for row in cursor.fetchall()]

    def get_collaboration_song_details(self, artist1_id: str, artist2_id: str) -> List[Dict]:
        """
        Like get_collaboration_songs, but each song also carries the full list
        of artists credited on that recording (for showing the lineup).

        Returns:
            List of {'name': str, 'collaborators': List[str]}
        """
        if artist1_id > artist2_id:
            artist1_id, artist2_id = artist2_id, artist1_id

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.song_name, s.collaborators
                FROM songs s
                JOIN collaborations c ON s.collaboration_id = c.id
                WHERE c.artist1_id = ? AND c.artist2_id = ?
            """, (artist1_id, artist2_id))

            details = []
            for row in cursor.fetchall():
                try:
                    collabs = json.loads(row['collaborators']) if row['collaborators'] else []
                except (ValueError, TypeError):
                    collabs = []
                details.append({'name': row['song_name'], 'collaborators': collabs})
            return details

    def get_stats(self) -> Dict:
        """Get database statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as count FROM artists")
            artist_count = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM collaborations")
            collab_count = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM songs")
            song_count = cursor.fetchone()['count']

            return {
                'total_artists': artist_count,
                'total_collaborations': collab_count,
                'total_songs': song_count
            }

    def get_all_artist_ids(self) -> List[str]:
        """Get all artist IDs in the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM artists")
            return [row['id'] for row in cursor.fetchall()]


# For BFS pathfinding - builds adjacency list from database
def build_adjacency_list(db: CollaborationDatabase) -> Dict[str, List[str]]:
    """
    Build an adjacency list from the database for pathfinding.

    Args:
        db: CollaborationDatabase instance

    Returns:
        Dict mapping artist_id to list of collaborator IDs
    """
    adjacency = {}

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT artist1_id, artist2_id FROM collaborations")

        for row in cursor.fetchall():
            a1, a2 = row['artist1_id'], row['artist2_id']

            if a1 not in adjacency:
                adjacency[a1] = []
            if a2 not in adjacency:
                adjacency[a2] = []

            adjacency[a1].append(a2)
            adjacency[a2].append(a1)

    return adjacency
