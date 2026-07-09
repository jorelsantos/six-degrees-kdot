"""
U6 — Serving database export for Cloudflare D1 (plan 2026-07-09-001, KTD6).

Builds a slim, denormalized SQLite file from the master DB — one row per
artist carrying everything the Worker (U7) needs for a point-lookup connection
walk and FTS5 search, instead of importing the full 192MB master schema. Also
writes a plain-text `.sql` dump of that data (D1's `wrangler d1 execute
--file=` only accepts SQL text, not a binary SQLite file — there is no
`wrangler d1 import` subcommand in current wrangler, despite that being the
intuitive name), and a SEPARATE post-import SQL file for the FTS5 search
index, because D1 additionally breaks on a single import containing virtual
tables (a second, real Cloudflare gotcha) — the FTS5 table must be created
AFTER the base data lands in D1, via its own `execute --file=` call.

Sentinel handling differs by column (this is load-bearing, not arbitrary):
- `photo_url`: the PHOTO_NONE_SENTINEL collapses to NULL. Photos are never
  lazily re-resolved at runtime, so "confirmed no photo" and "never checked"
  are behaviorally identical to a visitor (both render the initials
  fallback) — one NULL contract is simpler for the Worker/frontend.
- `via_track_id`: the NO_TRACK_SENTINEL passes through UNCHANGED (as the
  literal string, matching the master DB's own convention). The Worker's
  lazy resolve-track endpoint (U7) must be able to tell "confirmed no match,
  don't re-search" (the sentinel) apart from "never checked, may still
  resolve" (NULL) — collapsing them would make every unresolved song get
  re-searched against Spotify on every cold cache miss.

Re-running this script is safe and cheap (per KTD6/Risks: D1 is a cache
layer for the lazily-resolved via_track_id column; re-exporting overwrites
it harmlessly since re-resolution is self-healing) — this is the mechanism
for picking up a fresh photo/track-ID pre-bake or a future data refresh.

CLI:
    python3 scripts/export_serving_db.py --db data/collaboration_network_mb.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
from database import CollaborationDatabase, PHOTO_NONE_SENTINEL  # noqa: E402

DEFAULT_OUTPUT_DIR = _ROOT / "worker" / "export"
SERVING_DB_FILENAME = "serving.db"  # for local inspection/testing (sqlite3 CLI, tests)
SERVING_SQL_FILENAME = "serving.sql"  # what actually gets fed to `wrangler d1 execute --file=`
FTS5_SETUP_FILENAME = "fts5_setup.sql"

SCHEMA_SQL = """
CREATE TABLE artists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_norm TEXT,
    popularity INTEGER,
    degree INTEGER,
    photo_url TEXT,
    kendrick_distance INTEGER,
    predecessor_id TEXT,
    via_song_title TEXT,
    via_song_collaborators TEXT,
    via_track_id TEXT
);
CREATE INDEX idx_artists_name_norm ON artists(name_norm);
CREATE INDEX idx_artists_predecessor ON artists(predecessor_id);

CREATE TABLE aliases (
    artist_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_norm TEXT,
    UNIQUE(artist_id, alias)
);
CREATE INDEX idx_aliases_artist ON aliases(artist_id);
CREATE INDEX idx_aliases_norm ON aliases(alias_norm);
"""


def _make_idempotent(dump: str) -> str:
    """Rewrite a stock `iterdump()` SQL dump into a form that is safe to run
    against D1 more than once — so an import interrupted for ANY reason
    (network blip, Ctrl-C, or hitting D1's free-tier 100k-rows/day write cap
    partway) is recovered by simply re-running the SAME command, with no
    manual cleanup and no confusing "table already exists" / duplicate-row
    errors.

    Three transforms:
    - Strip the `BEGIN TRANSACTION;`/`COMMIT;` wrapper so statements apply
      incrementally. Without this, a single atomic transaction that fails on
      the write cap would roll ALL rows back, and the re-run would restart
      from zero and hit the same wall forever. Incremental application lets
      the ~100k rows that landed on day one persist.
    - `CREATE TABLE`/`CREATE INDEX` -> `... IF NOT EXISTS` so re-running does
      not error on the objects already created.
    - `INSERT INTO` -> `INSERT OR IGNORE INTO` so rows already present (by the
      artists PRIMARY KEY / the aliases UNIQUE constraint) are skipped, not
      duplicated. A skipped row is not a write, so the re-run spends its daily
      write budget only on the rows that still need inserting.
    """
    dump = dump.replace("BEGIN TRANSACTION;", "").replace("COMMIT;", "")
    dump = dump.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ")
    dump = dump.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ")
    dump = dump.replace("INSERT INTO ", "INSERT OR IGNORE INTO ")
    return dump.strip() + "\n"

# Emitted as a SEPARATE file, applied AFTER `wrangler d1 import` completes —
# D1's export/import breaks on dumps containing virtual tables.
FTS5_SETUP_SQL = """
DROP TABLE IF EXISTS search_fts;
CREATE VIRTUAL TABLE search_fts USING fts5(artist_id UNINDEXED, term);
INSERT INTO search_fts(artist_id, term) SELECT id, name FROM artists;
INSERT INTO search_fts(artist_id, term) SELECT artist_id, alias FROM aliases WHERE alias IS NOT NULL;
"""


def _clean_photo(photo_url: Optional[str]) -> Optional[str]:
    """Sentinel and unchecked both mean 'no photo' to a visitor — collapse
    to one NULL contract (see module docstring)."""
    if not photo_url or photo_url == PHOTO_NONE_SENTINEL:
        return None
    return photo_url


def build_serving_db(db: CollaborationDatabase, output_path: Path) -> int:
    """Write a fresh slim SQLite file at `output_path` (overwritten if it
    already exists — this export is always a full rebuild, never a partial
    merge). Returns the number of artist rows written."""
    if output_path.exists():
        output_path.unlink()

    rows = db.get_serving_export_rows()
    aliases = db.get_all_aliases()

    conn = sqlite3.connect(str(output_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO artists (id, name, name_norm, popularity, degree,
                                 photo_url, kendrick_distance, predecessor_id,
                                 via_song_title, via_song_collaborators, via_track_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["id"], r["name"], r["name_norm"], r["popularity"], r["degree"],
                    _clean_photo(r["photo_url"]), r["kendrick_distance"], r["predecessor_id"],
                    r["via_song_title"], r["via_song_collaborators"],
                    r["via_track_id"],  # sentinel passes through unchanged, see module docstring
                )
                for r in rows
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO aliases (artist_id, alias, alias_norm) VALUES (?, ?, ?)",
            [(a["artist_id"], a["alias"], a["alias_norm"]) for a in aliases],
        )
        conn.commit()
    finally:
        conn.close()

    return len(rows)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export the slim Cloudflare D1 serving DB.")
    parser.add_argument("--db", required=True, help="Path to the built SQLite DB.")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_DIR),
                        help="Output directory for the serving DB + FTS5 setup SQL.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: DB not found at {db_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    serving_path = out_dir / SERVING_DB_FILENAME
    sql_path = out_dir / SERVING_SQL_FILENAME
    fts5_path = out_dir / FTS5_SETUP_FILENAME

    db = CollaborationDatabase(str(db_path))
    count = build_serving_db(db, serving_path)

    conn = sqlite3.connect(str(serving_path))
    try:
        sql_path.write_text(_make_idempotent("\n".join(conn.iterdump())))
    finally:
        conn.close()
    fts5_path.write_text(FTS5_SETUP_SQL)

    size_mb = serving_path.stat().st_size / (1024 * 1024)
    sql_size_mb = sql_path.stat().st_size / (1024 * 1024)
    print(f"Exported {count} artist rows -> {serving_path} ({size_mb:.1f} MB)")
    print(f"SQL dump for D1 -> {sql_path} ({sql_size_mb:.1f} MB)")
    print(f"FTS5 post-import setup written -> {fts5_path}")
    print()
    print("Local dev:  wrangler d1 execute rabbit-hole-serving --local  --file=" + str(sql_path))
    print("            wrangler d1 execute rabbit-hole-serving --local  --file=" + str(fts5_path))
    print("Deploy:     wrangler d1 execute rabbit-hole-serving --remote --file=" + str(sql_path))
    print("            wrangler d1 execute rabbit-hole-serving --remote --file=" + str(fts5_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
