"""
U5 — Tier A static demo exporter (plan 2026-07-09-001).

Walks each showcase artist's precomputed path to Kendrick (src/path_tree.py)
and emits one JSON file per artist under frontend/public/demo/, plus an index
listing every showcase artist (name, id, photo, distance) for the showcase
grid. Zero backend at runtime — the Next.js demo page fetches these static
files directly; nothing here runs after `next build`.

Showcase artists are configured in scripts/showcase_artists.json (name + id
pairs). Edit that file to change the set, then re-run this script — and
force-resolve the new artist's chain hops first via the pre-bakes' seed-ids
flag (src/photo_prebake.py / src/track_prebake.py --seed-ids), since a
showcase artist's chain must be fully baked before it can export cleanly.

CLI:
    python3 scripts/export_demo.py --db data/collaboration_network_mb.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
from database import CollaborationDatabase, NO_TRACK_SENTINEL, PHOTO_NONE_SENTINEL  # noqa: E402

DEFAULT_SHOWCASE_CONFIG = _ROOT / "scripts" / "showcase_artists.json"
DEFAULT_OUTPUT_DIR = _ROOT / "frontend" / "public" / "demo"
MAX_CHAIN_HOPS = 10  # guard against an unexpected predecessor cycle


def _clean_photo(photo_url: Optional[str]) -> Optional[str]:
    if not photo_url or photo_url == PHOTO_NONE_SENTINEL:
        return None
    return photo_url


def _clean_track_id(track_id: Optional[str]) -> Optional[str]:
    if not track_id or track_id == NO_TRACK_SENTINEL:
        return None
    return track_id


def build_chain(db: CollaborationDatabase, artist_id: str) -> Dict:
    """
    Walk the precomputed path tree from `artist_id` to Kendrick (following
    `predecessor_id`, same direction the live app's path[0]->path[last] runs:
    searched artist first, Kendrick last).

    Returns {'degrees', 'path': [{'id','name','photo_url'}, ...], 'hops':
    [{'song_name','track_id','artists'}, ...]} — len(hops) == len(path) - 1;
    hops[i] is the connection between path[i] and path[i+1].

    Raises ValueError if the artist has no path-tree row (U2 hasn't run) or
    the walk exceeds MAX_CHAIN_HOPS (a cycle would indicate corrupt data —
    see path_tree.validate()).
    """
    path: List[Dict] = []
    hops: List[Dict] = []

    current = artist_id
    for _ in range(MAX_CHAIN_HOPS):
        row = db.get_path_tree_row(current)
        artist = db.get_artist(current)
        # kendrick_distance NULL means "never reached by path_tree.py" for
        # every artist except Kendrick himself (distance 0) — an artist row
        # can exist (added after the last precompute run) with an all-NULL
        # path-tree row, which must not be mistaken for "this is Kendrick".
        if row is None or artist is None or row["kendrick_distance"] is None:
            raise ValueError(f"artist {current!r} missing path-tree data — run path_tree.py first")
        photo_urls = db.get_photo_urls([current])
        path.append({
            "id": current,
            "name": artist["name"],
            "photo_url": _clean_photo(photo_urls.get(current)),
        })
        if row["predecessor_id"] is None:
            break
        song = db.get_song(row["via_song_id"]) if row["via_song_id"] else None
        hops.append({
            "song_name": song["name"] if song else None,
            "track_id": _clean_track_id(song["spotify_track_id"]) if song else None,
            "artists": song["collaborators"] if song else [],
        })
        current = row["predecessor_id"]
    else:
        raise ValueError(f"chain from {artist_id!r} exceeded {MAX_CHAIN_HOPS} hops — possible cycle")

    return {"degrees": len(path) - 1, "path": path, "hops": hops}


def export_demo(db: CollaborationDatabase, showcase: List[Dict], output_dir: Path,
                log=print) -> List[Dict]:
    """Export one JSON file per showcase artist plus an index.json. Returns
    the index entries actually written — an artist whose chain isn't baked
    yet is logged and skipped rather than aborting the whole export."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index: List[Dict] = []

    for entry in showcase:
        artist_id = entry["id"]
        try:
            chain = build_chain(db, artist_id)
        except ValueError as exc:
            log(f"warning: skipping {entry.get('name', artist_id)!r}: {exc}")
            continue

        (output_dir / f"{artist_id}.json").write_text(json.dumps(chain, indent=2))
        index.append({
            "id": artist_id,
            "name": chain["path"][0]["name"],
            "photo_url": chain["path"][0]["photo_url"],
            "degrees": chain["degrees"],
        })

    (output_dir / "index.json").write_text(json.dumps(index, indent=2))
    return index


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export the Tier A static demo JSON.")
    parser.add_argument("--db", required=True, help="Path to the built SQLite DB.")
    parser.add_argument("--showcase", default=str(DEFAULT_SHOWCASE_CONFIG),
                        help="Path to the showcase artist config JSON.")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_DIR),
                        help="Output directory for the exported JSON.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: DB not found at {db_path}", file=sys.stderr)
        return 1
    showcase_path = Path(args.showcase)
    if not showcase_path.exists():
        print(f"error: showcase config not found at {showcase_path}", file=sys.stderr)
        return 1

    showcase = json.loads(showcase_path.read_text())
    db = CollaborationDatabase(str(db_path))
    index = export_demo(db, showcase, Path(args.out))

    print(f"Exported {len(index)}/{len(showcase)} showcase chains to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
