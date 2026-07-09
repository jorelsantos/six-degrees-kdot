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
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Optional

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


# One whole `iterdump()` INSERT statement: `INSERT INTO "tbl" VALUES(...);`.
# DOTALL so a value containing a newline can't break the match; the value
# tuple `(...)` is captured opaquely, preserving iterdump's own quoting/escaping.
_INSERT_RE = re.compile(r'^INSERT INTO (?P<tbl>\S+) VALUES\s*(?P<vals>\(.*\))\s*;\s*$', re.DOTALL)

_BATCH_SIZE = 500
# D1 caps a single SQL statement at ~100 KB, so cap each batch's byte size well
# under that (rows vary in width — a long collaborator-JSON row is much bigger
# than a short alias row, so a fixed row count alone can't guarantee the bound).
_BATCH_BYTES = 60_000


def _dump_to_batched_sql(
    statements: Iterable[str],
    batch_size: int = _BATCH_SIZE,
    batch_bytes: int = _BATCH_BYTES,
) -> str:
    """Turn a `sqlite3.iterdump()` statement stream into idempotent D1 SQL with
    multi-row INSERT batches.

    Why batch: a stock dump emits one INSERT per row (~150k statements for the
    full serving DB), which `wrangler d1 execute --file=` applies painfully
    slowly. Coalescing rows into `INSERT ... VALUES (…),(…),…;` cuts that to a
    few thousand statements — seconds, not minutes. A batch is flushed at
    whichever limit hits first: `batch_size` rows or `batch_bytes` of accumulated
    tuples (the byte cap keeps every statement under D1's ~100 KB limit).

    Batching operates on whole iterdump *statements*, never on joined lines, so
    a value containing a newline can never split a statement, and each value
    tuple is carried through verbatim (iterdump already escaped quotes/apostrophes).

    Idempotence transforms (same intent as the prior line-based version, so a
    re-run after any interruption is recovered by re-running the same command):
    - drop the `BEGIN TRANSACTION;`/`COMMIT;` wrapper so statements apply
      incrementally (a mid-run failure keeps the rows that already landed);
    - `CREATE TABLE`/`CREATE INDEX` -> `... IF NOT EXISTS`;
    - `INSERT INTO` -> `INSERT OR IGNORE INTO` so rows already present (artists
      PRIMARY KEY / aliases UNIQUE) are skipped, not duplicated.
    """
    out: List[str] = []
    batch_tbl: Optional[str] = None
    batch_vals: List[str] = []
    batch_len = 0

    def flush() -> None:
        nonlocal batch_tbl, batch_vals, batch_len
        if batch_tbl is not None and batch_vals:
            out.append(
                f"INSERT OR IGNORE INTO {batch_tbl} VALUES\n"
                + ",\n".join(batch_vals)
                + ";"
            )
        batch_tbl, batch_vals, batch_len = None, [], 0

    for stmt in statements:
        s = stmt.strip()
        if s in ("BEGIN TRANSACTION;", "COMMIT;"):
            continue
        m = _INSERT_RE.match(s)
        if m:
            tbl = m.group("tbl")
            vals = m.group("vals")
            vals_bytes = len(vals.encode("utf-8"))  # true byte size — names may be multibyte
            if (
                tbl != batch_tbl
                or len(batch_vals) >= batch_size
                or (batch_vals and batch_len + vals_bytes > batch_bytes)
            ):
                flush()
                batch_tbl = tbl
            batch_vals.append(vals)
            batch_len += vals_bytes + 2
            continue
        # Non-INSERT statement: flush the pending batch, then emit it made
        # idempotent. A stray INSERT the batch regex didn't match also lands
        # here — give it the same INSERT OR IGNORE form so a re-run can't
        # conflict on it (preserves the idempotence guarantee for every row).
        flush()
        if s.startswith("CREATE TABLE "):
            s = s.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
        elif s.startswith("CREATE INDEX "):
            s = s.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
        elif s.startswith("INSERT INTO "):
            s = s.replace("INSERT INTO ", "INSERT OR IGNORE INTO ", 1)
        out.append(s)

    flush()
    return "\n".join(out).strip() + "\n"

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
        sql_path.write_text(_dump_to_batched_sql(conn.iterdump()))
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
