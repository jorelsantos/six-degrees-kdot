"""
SQLite Database Module for Six Degrees of Kendrick Lamar

This module handles all database operations for storing the artist
collaboration network in SQLite format for scalability and portability.
"""

import re
import sqlite3
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager

# Fuzzy fallback: fires only when the exact/substring SQL search is thin,
# so a typo like "Maria the scientist" still resolves "Mariah the Scientist".
FUZZY_MIN_RESULTS = 3   # run the fuzzy pass only when SQL returns fewer than this
FUZZY_SCORE_CUTOFF = 72  # 0-100; conservative so gibberish returns nothing

# Cross-tier prominence override (KTD2): a substring/fuzzy candidate outranks an
# exact/prefix hit when its prominence is >= this factor times the exact hit's.
# This is what makes "Big" resolve to The Notorious B.I.G. instead of a 1-collab
# artist literally named "Big" — tier ordering alone can never do that.
CROSS_TIER_OVERRIDE_FACTOR = 50

# Popularity becomes the primary within-tier ranking key only once this fraction
# of artists has been enriched (pop_enriched=1). Below it, degree is primary —
# otherwise an enriched minor artist (25k listeners) outranks an unenriched
# superstar whose popularity is still the schema default 0.
ENRICHED_COVERAGE_THRESHOLD = 0.9

# Sentinel stored in songs.spotify_track_id when the enrichment pass searched
# for a song but found no acceptable match. Distinct from NULL ("not yet
# checked") so the pass is resumable and re-runs make zero Spotify calls (R2).
NO_TRACK_SENTINEL = "none"

# Sentinel stored in artists.photo_url when the photo waterfall was fully
# consulted and no source had an image (plan 010, KTD2). Distinct from NULL
# ("unchecked, or a source errored — retry later") so a genuine no-photo artist
# is never re-queried, while transient failures stay retryable.
PHOTO_NONE_SENTINEL = "none"

# Characters deleted outright by fold_name (intra-word marks: "B.I.G." -> "big",
# "Lil’ Flip" -> "lil flip"). Everything else non-alphanumeric becomes a space
# ("JAY‐Z" -> "jay z", "Tyler, The Creator" -> "tyler the creator").
_FOLD_DELETE_RE = re.compile(r"[.'’ʼ]")
_FOLD_SPACE_RE = re.compile(r"[^a-z0-9]+")


def fold_name(text: str) -> str:
    """
    Normalize an artist name (or query) for matching: lowercase, strip accents,
    class-differentiated punctuation — dots/apostrophes DELETE, separators
    (hyphens incl. Unicode variants, commas, slashes...) become SPACES, then
    whitespace collapses. The asymmetry is load-bearing: a uniform
    punctuation->space rule would fold "B.I.G." to "b i g" and never match
    "big"; uniform deletion would fold "JAY‐Z" to "jayz" and never match
    "jay z". A name that folds to empty (e.g. "!!!") falls back to its raw
    lowercase so it can still match itself.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    s = _FOLD_DELETE_RE.sub("", s)
    s = _FOLD_SPACE_RE.sub(" ", s)
    s = " ".join(s.split())
    return s if s else text.lower().strip()


# Backward-compatible alias: the fuzzy matcher's processor is the same fold.
_fold_for_match = fold_name


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
        # Lazily-built {artist_id: name} map for the fuzzy fallback. Cached on the
        # instance; in the app the DB is an @st.cache_resource singleton, so this
        # is built at most once per process.
        self._name_choices: Optional[Dict[str, str]] = None
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

            # Artists table (nodes). `name_norm` is the fold_name() of `name`
            # (accent/punctuation-blind matching); `degree` is the precomputed
            # collaboration count (ranking key + UI label — refreshed by
            # refresh_degrees(), never assumed static).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artists (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    popularity INTEGER DEFAULT 0,
                    genres TEXT DEFAULT '[]',
                    crawled INTEGER DEFAULT 0,
                    name_norm TEXT,
                    degree INTEGER DEFAULT 0
                )
            """)

            # Migration guard: add `crawled` to databases created before this column existed.
            cursor.execute("PRAGMA table_info(artists)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            if "crawled" not in existing_columns:
                cursor.execute("ALTER TABLE artists ADD COLUMN crawled INTEGER DEFAULT 0")

            # Migration guard: `pop_enriched` marks an artist whose popularity has
            # been resolved by the popularity-enrichment pass (Last.fm listeners,
            # or a graph-degree fallback). Needed because `popularity = 0` is
            # ambiguous — it can mean "no listeners" OR "not yet checked" — so a
            # distinct marker is what makes enrichment runs resumable.
            if "pop_enriched" not in existing_columns:
                cursor.execute("ALTER TABLE artists ADD COLUMN pop_enriched INTEGER DEFAULT 0")

            # Migration guard + one-time backfill: `name_norm` for legacy DBs.
            # Folding needs Python (unicodedata), so backfill row-by-row here;
            # new inserts populate it in add_artist and never hit this path.
            need_degree_refresh = False
            if "name_norm" not in existing_columns:
                cursor.execute("ALTER TABLE artists ADD COLUMN name_norm TEXT")
                cursor.execute("SELECT id, name FROM artists")
                rows = [(fold_name(r["name"]), r["id"]) for r in cursor.fetchall()]
                cursor.executemany("UPDATE artists SET name_norm = ? WHERE id = ?", rows)
            if "degree" not in existing_columns:
                cursor.execute("ALTER TABLE artists ADD COLUMN degree INTEGER DEFAULT 0")
                need_degree_refresh = True

            # Migration guard: `photo_url` caches an artist's resolved photo
            # (plan 2026-07-06-010, KTD2). NULL = unchecked OR a source errored
            # last time (retry later); a validated image URL = resolved; the
            # PHOTO_NONE_SENTINEL "none" = the full waterfall was consulted and
            # every source missed (never re-queried). Same checked-vs-default
            # idiom as spotify_track_id/preview_source.
            if "photo_url" not in existing_columns:
                cursor.execute("ALTER TABLE artists ADD COLUMN photo_url TEXT")

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

            # Migration guard: `spotify_track_id` is resolved once by the
            # build-time enrichment pass (src/spotify_enrich.py) and read at
            # render time to embed Spotify's player — runtime never calls
            # Spotify's API (plan 2026-07-06-004, R2/KTD2). NULL = "not yet
            # checked"; a real track id or the literal "none" sentinel = "checked"
            # (the sentinel is what makes the pass resumable — same idiom as
            # `pop_enriched` distinguishing checked from the ambiguous default).
            if "spotify_track_id" not in song_cols:
                cursor.execute("ALTER TABLE songs ADD COLUMN spotify_track_id TEXT")

            # Migration guard: `preview_source` records which waterfall tier a
            # song's preview resolved to (plan 2026-07-06-008, KTD3): NULL = not
            # yet checked; 'spotify'|'itunes'|'deezer' = resolved to that source
            # (the audio URL is re-resolved fresh at serve, since preview URLs
            # expire — we persist the identity/source, not the volatile URL);
            # 'none' = checked, no preview anywhere. This is what lets the
            # edge-preview endpoint skip re-walking already-checked songs.
            if "preview_source" not in song_cols:
                cursor.execute("ALTER TABLE songs ADD COLUMN preview_source TEXT")

            # Artist aliases (alternate names -> canonical artist node). One row
            # per (artist, alias); lets a search for "Kanye West" resolve to the
            # canonical "Ye" node. Populated only by the MusicBrainz build; the
            # legacy Spotify DB simply has an empty table (CREATE IF NOT EXISTS),
            # so both DBs load under one schema and alias lookups no-op there.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artist_aliases (
                    artist_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    alias_norm TEXT,
                    FOREIGN KEY (artist_id) REFERENCES artists(id),
                    UNIQUE(artist_id, alias)
                )
            """)

            # Migration guard + backfill: `alias_norm` for legacy DBs (same
            # rationale as name_norm above).
            cursor.execute("PRAGMA table_info(artist_aliases)")
            alias_cols = {row[1] for row in cursor.fetchall()}
            if "alias_norm" not in alias_cols:
                cursor.execute("ALTER TABLE artist_aliases ADD COLUMN alias_norm TEXT")
                cursor.execute("SELECT rowid, alias FROM artist_aliases")
                arows = [(fold_name(r["alias"]), r["rowid"]) for r in cursor.fetchall()]
                cursor.executemany(
                    "UPDATE artist_aliases SET alias_norm = ? WHERE rowid = ?", arows)

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
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_artist_name_norm
                ON artists(name_norm)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alias_norm
                ON artist_aliases(alias_norm)
            """)

        # Degree backfill runs outside the schema transaction: it reuses the
        # same single-pass GROUP BY as refresh_degrees(), and a legacy DB being
        # opened for the first time after this migration needs real counts
        # immediately (degree is a ranking key, not an optimization).
        if need_degree_refresh:
            self.refresh_degrees()

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
                INSERT OR IGNORE INTO artists (id, name, popularity, genres, name_norm)
                VALUES (?, ?, ?, ?, ?)
            """, (artist_id, name, popularity, json.dumps(genres), fold_name(name)))

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
                INSERT OR IGNORE INTO artist_aliases (artist_id, alias, alias_norm)
                VALUES (?, ?, ?)
            """, (artist_id, alias.strip(), fold_name(alias.strip())))

    def add_artist_aliases(self, artist_id: str, aliases: List[str]) -> None:
        """Bulk variant of add_artist_alias for one artist."""
        rows = [(artist_id, a.strip(), fold_name(a.strip()))
                for a in (aliases or []) if a and a.strip()]
        if not rows:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR IGNORE INTO artist_aliases (artist_id, alias, alias_norm)
                VALUES (?, ?, ?)
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
        # NOTE (plan 2026-07-06-002, U2): this function is deliberately NOT
        # routed through resolve_artist. scripts/verify_coverage.py depends on
        # exact-name/exact-alias semantics to measure the no-connection rate —
        # fuzzy delegation would silently corrupt that instrument. It gains
        # only duplicate-safety: 3,927 name groups share a name (e.g. three
        # "The Game" nodes), so the exact branch orders by prominence instead
        # of returning an arbitrary row.
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, popularity, genres
                FROM artists WHERE name = ? COLLATE NOCASE
                ORDER BY popularity DESC, degree DESC
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

            # Fall back to an exact alias match (e.g. "Kanye West" -> "Ye"),
            # resolving to the canonical artist node. Prefer the more prominent
            # artist when an alias is shared by several.
            cursor.execute("""
                SELECT a.id, a.name, a.popularity, a.genres
                FROM artist_aliases al
                JOIN artists a ON a.id = al.artist_id
                WHERE al.alias = ? COLLATE NOCASE
                ORDER BY a.popularity DESC, a.degree DESC
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

    def resolve_artist(self, query: str, limit: int = 10) -> List[Dict]:
        """
        THE single resolution pipeline (plan 2026-07-06-002, KTD1/KTD2): every
        consumer — the suggestions list AND the submit button — ranks candidates
        through this one function, so the two can never disagree about who a
        query means. Returns [] when nothing plausible matches (callers must
        handle empty; never index an unchecked [0]).

        Ranking: match tier (exact/prefix on folded name OR alias = 0,
        substring = 1, fuzzy = 2), then prominence within the tier, then name.
        Prominence = popularity once enrichment coverage clears
        ENRICHED_COVERAGE_THRESHOLD, else degree-primary (a half-enriched DB
        must not rank an enriched minor above an unenriched superstar).
        Finally the cross-tier override re-ranks the head: a dramatically more
        prominent lower-tier candidate (>= CROSS_TIER_OVERRIDE_FACTOR x)
        replaces an obscure exact hit — that override IS the "prominence wins"
        product decision.
        """
        q = fold_name(query)
        if not q:
            return []

        pop_primary = self.enriched_coverage() >= ENRICHED_COVERAGE_THRESHOLD
        prom_order = ("a.popularity DESC, a.degree DESC" if pop_primary
                      else "a.degree DESC, a.popularity DESC")

        like = f"%{q}%"
        prefix = f"{q}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # One row per canonical artist (GROUP BY a.id); MIN over the alias
            # join takes the BEST tier across the canonical name and every
            # alias, so "Biggie" prefix-matching the "Biggie Smalls" alias puts
            # The Notorious B.I.G. in tier 0 (R5) instead of ranking junk
            # "Biggie Bash"-style name matches above him.
            cursor.execute(f"""
                SELECT a.id, a.name, a.popularity, a.genres, a.degree,
                    MIN(CASE
                        WHEN a.name_norm LIKE ? THEN 0
                        WHEN al.alias_norm LIKE ? THEN 0
                        ELSE 1
                    END) AS tier
                FROM artists a
                LEFT JOIN artist_aliases al ON al.artist_id = a.id
                WHERE a.name_norm LIKE ?
                   OR al.alias_norm LIKE ?
                GROUP BY a.id
                ORDER BY tier ASC, {prom_order}, a.name ASC
                LIMIT ?
            """, (prefix, prefix, like, like, limit))
            results = [self._candidate(row) for row in cursor.fetchall()]

        # Typo tolerance: only when the SQL pass is thin do we pay for fuzzy.
        # Correctly-spelled queries stay on the fast indexed path.
        if len(results) < FUZZY_MIN_RESULTS:
            seen = {r['id'] for r in results}
            for row in self._fuzzy_search(query, limit):
                if row['id'] not in seen:
                    results.append(row)
                    seen.add(row['id'])
            results = results[:limit]

        return self._apply_cross_tier_override(results, pop_primary)

    @staticmethod
    def _prominence(candidate: Dict, pop_primary: bool) -> int:
        return candidate['popularity'] if pop_primary else candidate['degree']

    def _apply_cross_tier_override(self, results: List[Dict],
                                   pop_primary: bool) -> List[Dict]:
        """
        KTD2 cross-tier override: if the head is a tier-0 (exact/prefix) hit but
        a lower-tier candidate is >= CROSS_TIER_OVERRIDE_FACTOR x more
        prominent, the prominent candidate takes the head. Implements R3
        ("prominence wins"); without it, an obscure artist literally named
        "Big" would beat The Notorious B.I.G. forever.
        """
        if len(results) < 2 or results[0].get('tier', 0) != 0:
            return results
        head_prom = max(self._prominence(results[0], pop_primary), 1)
        best_lower = max(
            (c for c in results[1:] if c.get('tier', 0) > 0),
            key=lambda c: self._prominence(c, pop_primary),
            default=None,
        )
        if best_lower is not None and \
                self._prominence(best_lower, pop_primary) >= CROSS_TIER_OVERRIDE_FACTOR * head_prom:
            results = [best_lower] + [c for c in results if c is not best_lower]
        return results

    @staticmethod
    def _candidate(row) -> Dict:
        return {
            'id': row['id'],
            'name': row['name'],
            'popularity': row['popularity'],
            'genres': json.loads(row['genres']),
            'degree': row['degree'],
            'tier': row['tier'] if 'tier' in row.keys() else 2,
        }

    def search_artists(self, query: str, limit: int = 10) -> List[Dict]:
        """Thin wrapper over resolve_artist — kept for API compatibility."""
        return self.resolve_artist(query, limit)

    def _name_choices_map(self) -> Dict[str, str]:
        """Lazily build and cache {artist_id: name} for fuzzy matching."""
        if self._name_choices is None:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM artists")
                self._name_choices = {row["id"]: row["name"] for row in cursor.fetchall()}
        return self._name_choices

    def _fuzzy_search(self, query: str, limit: int) -> List[Dict]:
        """
        Fuzzy-rank artist names against a (likely misspelled) query using
        rapidfuzz, returning rows in the standard search shape ordered by match
        score. Returns [] if nothing clears FUZZY_SCORE_CUTOFF.
        """
        from rapidfuzz import process, fuzz

        choices = self._name_choices_map()
        if not choices:
            return []
        # Fold accents/case so "Beyonse" matches "Beyoncé" and "Sia" matches
        # "Sía" — accented names are everywhere in music.
        #
        # token_sort_ratio, not WRatio: WRatio's partial-ratio component scores a
        # short name 100 whenever it's a substring of the query (e.g. "Yon" is
        # inside "be-YON-se"), flooding results with 1-3 char junk. token_sort
        # scores the whole string, so a real typo ("beyonse" vs "beyonce") wins
        # and substrings don't. The substring/prefix cases are already served by
        # the SQL LIKE path; fuzzy only handles genuine misspellings.
        matches = process.extract(
            query, choices, scorer=fuzz.token_sort_ratio, processor=_fold_for_match,
            limit=limit, score_cutoff=FUZZY_SCORE_CUTOFF,
        )
        # matches: list of (name, score, artist_id), best first.
        ids = [artist_id for (_name, _score, artist_id) in matches]
        if not ids:
            return []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in ids)
            cursor.execute(f"""
                SELECT id, name, popularity, genres, degree FROM artists
                WHERE id IN ({placeholders})
            """, ids)
            by_id = {row["id"]: self._candidate(row) for row in cursor.fetchall()}
        # Preserve rapidfuzz's score order. Fuzzy rows are tier 2 by definition.
        out = [by_id[i] for i in ids if i in by_id]
        for c in out:
            c['tier'] = 2
        return out

    def refresh_degrees(self) -> None:
        """
        Recompute the `degree` column from live edges (single-pass GROUP BY).
        Called by the migration backfill AND at the end of every graph build —
        degree is a ranking key and a user-facing label, so a rebuilt DB must
        never ship zero/stale counts.
        """
        degrees = self.get_all_degrees()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE artists SET degree = 0")
            cursor.executemany(
                "UPDATE artists SET degree = ? WHERE id = ?",
                [(d, aid) for aid, d in degrees.items()])

    def enriched_coverage(self) -> float:
        """Fraction of artists whose popularity has been enriched (cached)."""
        if getattr(self, "_enriched_coverage", None) is None:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT AVG(COALESCE(pop_enriched, 0)) AS c FROM artists")
                row = cursor.fetchone()
                self._enriched_coverage = float(row["c"] or 0.0)
        return self._enriched_coverage

    def get_all_degrees(self) -> Dict[str, int]:
        """
        Return {artist_id: collaboration_count} for every node with at least one
        edge, computed in a single pass. Edges are undirected and stored once
        (artist1_id < artist2_id), so an artist's degree is the number of rows
        naming it in either column. Used as the popularity fallback/tiebreak and
        by the enrichment pass's --min-degree filter.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT artist_id, COUNT(*) AS degree FROM (
                    SELECT artist1_id AS artist_id FROM collaborations
                    UNION ALL
                    SELECT artist2_id AS artist_id FROM collaborations
                )
                GROUP BY artist_id
            """)
            return {row["artist_id"]: row["degree"] for row in cursor.fetchall()}

    def get_unenriched_artists(self) -> List[Dict]:
        """
        Return artists whose popularity has not yet been resolved by the
        enrichment pass ({'id', 'name'}), so a run can resume where it left off.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name FROM artists
                WHERE pop_enriched = 0 OR pop_enriched IS NULL
            """)
            return [{"id": row["id"], "name": row["name"]} for row in cursor.fetchall()]

    def set_popularity(self, artist_id: str, value: int) -> None:
        """Set an artist's popularity and mark them enriched (idempotent)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE artists SET popularity = ?, pop_enriched = 1 WHERE id = ?
            """, (int(value), artist_id))

    def set_popularity_bulk(self, rows: List[Tuple[str, int]]) -> None:
        """Bulk variant of set_popularity: rows of (artist_id, value)."""
        if not rows:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                UPDATE artists SET popularity = ?, pop_enriched = 1 WHERE id = ?
            """, [(int(v), aid) for aid, v in rows])

    def get_songs_without_track_id(self, min_degree: int = 0,
                                   limit: Optional[int] = None) -> List[Dict]:
        """
        Return songs whose Spotify track id hasn't been resolved yet
        (spotify_track_id IS NULL), so a run resumes where it left off. Each row
        is {'id', 'song_name', 'collaborators'} — the collaborators list feeds
        both the search term and the accept-logic.

        `min_degree` bounds runtime to songs on an edge touching a prominent
        artist (max endpoint degree >= N), leaving the long tail for a later full
        pass — the same knob as the popularity pass. `limit` caps the batch (used
        to measure a first pass, per Q1).
        """
        sql = """
            SELECT s.id, s.song_name, s.collaborators
            FROM songs s
            JOIN collaborations c ON s.collaboration_id = c.id
            JOIN artists a1 ON a1.id = c.artist1_id
            JOIN artists a2 ON a2.id = c.artist2_id
            WHERE s.spotify_track_id IS NULL
              AND MAX(a1.degree, a2.degree) >= ?
        """
        params: List = [min_degree]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            out = []
            for row in cursor.fetchall():
                try:
                    collabs = json.loads(row["collaborators"]) if row["collaborators"] else []
                except (ValueError, TypeError):
                    collabs = []
                out.append({
                    "id": row["id"],
                    "song_name": row["song_name"],
                    "collaborators": collabs,
                })
            return out

    def set_spotify_track_id(self, song_id: int, track_id: str) -> None:
        """Persist a resolved Spotify track id (or the NO_TRACK_SENTINEL) for a
        song row. Idempotent; marks the row as checked so re-runs skip it."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE songs SET spotify_track_id = ? WHERE id = ?",
                (track_id, song_id))

    def set_spotify_track_id_bulk(self, rows: List[Tuple[int, str]]) -> None:
        """Bulk variant of set_spotify_track_id: rows of (song_id, track_id)."""
        if not rows:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                "UPDATE songs SET spotify_track_id = ? WHERE id = ?",
                [(track_id, song_id) for song_id, track_id in rows])

    def set_preview_source(self, song_id: int, source: str) -> None:
        """Persist which waterfall tier a song's preview resolved to
        ('spotify'|'itunes'|'deezer'|'none'), marking it checked so the
        edge-preview endpoint skips re-walking it (plan 008, KTD3)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE songs SET preview_source = ? WHERE id = ?",
                (source, song_id))

    def get_photo_urls(self, artist_ids: List[str]) -> Dict[str, Optional[str]]:
        """Return {artist_id: photo_url} for the given ids, raw (a validated
        image URL, the PHOTO_NONE_SENTINEL "none", or None = unchecked). Only
        ids present in the DB appear in the result. Batched read for a
        connection's path artists (plan 010, U1)."""
        if not artist_ids:
            return {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in artist_ids)
            cursor.execute(
                f"SELECT id, photo_url FROM artists WHERE id IN ({placeholders})",
                list(artist_ids),
            )
            return {row["id"]: row["photo_url"] for row in cursor.fetchall()}

    def set_photo_url(self, artist_id: str, photo_url: str) -> None:
        """Persist a resolved photo URL (or the PHOTO_NONE_SENTINEL) for an
        artist, marking the row checked so it's never re-resolved. An artist
        left NULL (a transient source failure) is retried on a later request."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE artists SET photo_url = ? WHERE id = ?",
                (photo_url, artist_id))

    def set_photo_urls_bulk(self, rows: List[Tuple[str, str]]) -> None:
        """Bulk variant of set_photo_url: rows of (artist_id, photo_url)."""
        if not rows:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                "UPDATE artists SET photo_url = ? WHERE id = ?",
                [(photo_url, artist_id) for artist_id, photo_url in rows])

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
        of artists credited on that recording (for showing the lineup) plus the
        build-time-resolved `spotify_track_id` (the embed player's input). The
        id is the real track id, or None for songs that are unresolved (NULL) or
        resolved-to-no-match (the "none" sentinel) — both degrade to no player.

        Returns:
            List of {'id': int, 'name': str, 'collaborators': List[str],
                     'spotify_track_id': Optional[str]}
            The `id` is the song row id — the frontend hands it to the lazy
            resolve endpoint so a resolved-on-Play id persists to the right row.
        """
        if artist1_id > artist2_id:
            artist1_id, artist2_id = artist2_id, artist1_id

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.song_name, s.collaborators, s.spotify_track_id, s.preview_source
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
                track_id = row['spotify_track_id']
                # Normalize the sentinel/unchecked states to None so callers only
                # ever see a real, embeddable id or nothing.
                if track_id == NO_TRACK_SENTINEL:
                    track_id = None
                details.append({
                    'id': row['id'],
                    'name': row['song_name'],
                    'collaborators': collabs,
                    'spotify_track_id': track_id,
                    'preview_source': row['preview_source'],  # None|spotify|itunes|deezer|none
                })
            return details

    def get_song(self, song_id: int) -> Optional[Dict]:
        """
        Fetch one song row by id for the lazy resolve endpoint: its title, the
        credited lineup (for the search query + accept-logic), and the current
        spotify_track_id (raw — may be a real id, the "none" sentinel, or NULL).
        Returns None if the id is unknown.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, song_name, collaborators, spotify_track_id, preview_source
                FROM songs WHERE id = ?
            """, (song_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            try:
                collabs = json.loads(row['collaborators']) if row['collaborators'] else []
            except (ValueError, TypeError):
                collabs = []
            return {
                'id': row['id'],
                'name': row['song_name'],
                'collaborators': collabs,
                'spotify_track_id': row['spotify_track_id'],
                'preview_source': row['preview_source'],
            }

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


def disambiguate_labels(candidates: List[Dict]) -> List[str]:
    """
    Build display labels for suggestion candidates (plan 002, U4/R6). Unique
    names stay bare. Duplicate names get a collab-count qualifier
    ("The Game · 573 collabs"); candidates that STILL tie (same name AND same
    count — the HANA case) get a stable numbered suffix ordered by node id, so
    labels are always distinct and deterministic.
    """
    from collections import Counter

    # Collide on the DISPLAYED form, not the raw string: the suggestion
    # buttons render uppercase, so "HANA" and "Hana" are visual duplicates
    # even though they differ as strings.
    name_counts = Counter(c['name'].casefold() for c in candidates)
    qualified = []
    for c in candidates:
        if name_counts[c['name'].casefold()] == 1:
            qualified.append(c['name'])
        else:
            n = c.get('degree', 0)
            qualified.append(f"{c['name']} · {n} collab{'s' if n != 1 else ''}")

    label_positions: Dict[str, List[int]] = {}
    for i, label in enumerate(qualified):
        label_positions.setdefault(label.casefold(), []).append(i)
    for _label, positions in label_positions.items():
        if len(positions) > 1:
            # Stable ordering: number by node id so reruns agree.
            positions.sort(key=lambda i: candidates[i]['id'])
            for seq, i in enumerate(positions[1:], start=2):
                qualified[i] = f"{qualified[i]} ({seq})"
    return qualified


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
