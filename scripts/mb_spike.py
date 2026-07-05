"""
U8 — MusicBrainz validation spike.

Builds a *tiny* depth-2 collaboration graph around Kendrick Lamar from the
LIVE MusicBrainz API and writes it to a throwaway SQLite DB in the app's
schema (data/mb_spike.db). This is a proof-of-concept, NOT the real builder —
the real graph is built from the downloadable dump (U1-U3). The spike exists
only to prove the pipeline constructs a correct, usable graph on real data
before the half-day dump ingestion is committed.

Non-negotiable rules encoded here (see the migration plan, KTD2/KTD7/KTD8/KTD9):
- An edge exists ONLY when 2+ artists are co-credited on the same recording,
  and that recording IS the connecting song. No membership/relationship edges.
- Nodes are keyed on MBID, never display name ("Ye" and "Kanye West" are one).
- Recording versions dedup to one canonical connecting song per pair.

The pure functions (parse_credits, base_title, is_variant_title,
EdgeAccumulator, derive_edges) carry the edge logic and are unit-tested
offline against captured sample JSON in tests/test_mb_spike.py.

Usage (run in your own terminal so it's visible; ~tens of minutes at 1 req/sec):
    python3 scripts/mb_spike.py --depth 2 --out data/mb_spike.db \
        --max-pages 60 --max-degree1 40
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

# Make src/ importable whether run from repo root or elsewhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from database import CollaborationDatabase  # noqa: E402

USER_AGENT = "RabbitHole/0.1 (jorsanto@umich.edu)"
MB_BASE = "https://musicbrainz.org/ws/2"
KENDRICK_MBID = "381086ea-f511-4aba-bdf9-71c753dc5077"

# Be a good MusicBrainz citizen: the API allows ~1 req/sec. We space a touch
# more than that to leave headroom.
REQUEST_INTERVAL = 1.2

# ---------------------------------------------------------------------------
# Pure edge-derivation logic (unit-tested offline; no network)
# ---------------------------------------------------------------------------

# Markers that indicate a recording is a *variant* of a base song, not the
# canonical original. Used to prefer clean titles when deduping (KTD8).
_VARIANT_RE = re.compile(
    r"\b(remix|live|instrumental|acoustic|remaster(?:ed)?|edit|radio\s*edit|"
    r"extended|version|mix|demo|snippet|a\s*cappella|acapella|karaoke|"
    r"re-?recorded|reprise|edit\.|mono|stereo)\b",
    re.IGNORECASE,
)


def parse_credits(recording: dict) -> List[Tuple[str, str]]:
    """
    Extract co-credited artists from a MusicBrainz recording JSON object.

    Returns a list of (mbid, canonical_name) tuples, deduplicated by MBID and
    preserving credit order. Uses artist['name'] (the canonical artist name)
    as the display name so multiple credited names for one artist ("Ye" vs
    "Kanye West") collapse to a single node keyed on MBID (KTD7).
    """
    out: List[Tuple[str, str]] = []
    seen = set()
    for entry in recording.get("artist-credit", []) or []:
        artist = entry.get("artist") or {}
        mbid = artist.get("id")
        name = artist.get("name")
        if not mbid or not name:
            continue
        if mbid in seen:
            continue
        seen.add(mbid)
        out.append((mbid, name))
    return out


def is_variant_title(title: str) -> bool:
    """True if the title looks like a remix/live/instrumental/edit variant."""
    return bool(_VARIANT_RE.search(title or ""))


def base_title(title: str) -> str:
    """
    Normalize a recording title to a base key for deduping versions.

    Strips parentheticals/brackets, any " - ..." suffix (often "- Remix"),
    and "feat." clauses; lowercases and collapses whitespace/punctuation.
    "All Day (Remix)", "All Day - Radio Edit" and "All Day" all map to "all day".
    """
    t = title or ""
    t = re.sub(r"[\(\[].*?[\)\]]", " ", t)  # drop (...) / [...]
    t = re.sub(r"\s-\s.*$", " ", t)  # drop " - <suffix>"
    t = re.sub(r"\b(feat|ft|featuring|with)\b.*", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return " ".join(t.split())


class EdgeAccumulator:
    """
    Accumulates undirected co-credit edges and their candidate connecting
    songs, then emits a deduped, canonical representative-song list per edge.
    """

    def __init__(self) -> None:
        # (mbid_a, mbid_b) sorted -> list of raw recording titles
        self._edges: Dict[Tuple[str, str], List[str]] = {}
        # mbid -> display name (canonical artist name)
        self.names: Dict[str, str] = {}

    @staticmethod
    def _key(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def add_recording(self, credits: List[Tuple[str, str]], title: str) -> None:
        """Record every unordered artist pair on a recording as an edge."""
        for mbid, name in credits:
            self.names.setdefault(mbid, name)
        mbids = [c[0] for c in credits]
        for i in range(len(mbids)):
            for j in range(i + 1, len(mbids)):
                key = self._key(mbids[i], mbids[j])
                self._edges.setdefault(key, []).append(title)

    def neighbors(self, mbid: str) -> List[str]:
        result = []
        for a, b in self._edges:
            if a == mbid:
                result.append(b)
            elif b == mbid:
                result.append(a)
        return result

    def edges(self) -> Iterable[Tuple[str, str]]:
        return self._edges.keys()

    def representative_songs(self, a: str, b: str, cap: int = 5) -> List[str]:
        """
        Dedup version-sprawl into a small set of representative connecting
        songs. Groups candidate titles by base title; for each group picks the
        cleanest surface form (non-variant, else shortest). Returns up to `cap`
        distinct songs, canonical/original first (KTD8).
        """
        key = self._key(a, b)
        titles = self._edges.get(key, [])
        groups: Dict[str, List[str]] = {}
        for t in titles:
            groups.setdefault(base_title(t), []).append(t)

        reps: List[str] = []
        for _, variants in groups.items():
            # Prefer a non-variant title; tiebreak on shortest (cleanest) form.
            best = sorted(variants, key=lambda t: (is_variant_title(t), len(t)))[0]
            reps.append(best)

        # Order groups so cleaner/shorter canonical songs come first.
        reps.sort(key=lambda t: (is_variant_title(t), len(t)))
        return reps[:cap]


def derive_edges(recordings: Iterable[dict]) -> EdgeAccumulator:
    """Build an EdgeAccumulator from an iterable of recording JSON objects."""
    acc = EdgeAccumulator()
    for rec in recordings:
        credits = parse_credits(rec)
        if len(credits) < 2:
            continue  # solo recording -> no edge
        acc.add_recording(credits, rec.get("title", ""))
    return acc


# ---------------------------------------------------------------------------
# Live MusicBrainz client (rate-limited, descriptive User-Agent)
# ---------------------------------------------------------------------------


class MBClient:
    def __init__(self, interval: float = REQUEST_INTERVAL) -> None:
        self.interval = interval
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.request_count = 0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last = time.monotonic()

    def _get(self, path: str, params: dict) -> dict:
        params = {**params, "fmt": "json"}
        for attempt in range(5):
            self._throttle()
            self.request_count += 1
            resp = self.session.get(f"{MB_BASE}{path}", params=params, timeout=20)
            if resp.status_code == 503:
                # MusicBrainz asks us to back off. Respect it.
                wait = float(resp.headers.get("Retry-After", 2)) or 2
                time.sleep(min(wait, 10))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"MusicBrainz kept returning 503 for {path} {params}")

    def fetch_recordings(self, artist_mbid: str, max_pages: int) -> List[dict]:
        """Fetch recordings credited to an artist, with artist-credits, paged."""
        recordings: List[dict] = []
        offset = 0
        limit = 100
        for _ in range(max_pages):
            data = self._get(
                "/recording",
                {
                    "artist": artist_mbid,
                    "inc": "artist-credits",
                    "limit": limit,
                    "offset": offset,
                },
            )
            batch = data.get("recordings", [])
            recordings.extend(batch)
            total = data.get("recording-count", 0)
            offset += limit
            if offset >= total or not batch:
                break
        return recordings


# ---------------------------------------------------------------------------
# Depth-bounded BFS build
# ---------------------------------------------------------------------------


def build_spike(
    seed_mbid: str = KENDRICK_MBID,
    depth: int = 2,
    out_path: str = "data/mb_spike.db",
    max_pages: int = 60,
    max_degree1: Optional[int] = None,
    client: Optional[MBClient] = None,
) -> Dict:
    """
    BFS from the seed to `depth`, fetching co-credit edges live, then write the
    reachable subgraph into a fresh SQLite DB in the app's schema.

    `max_pages` caps recordings fetched per artist (100/page). `max_degree1`
    optionally caps how many degree-1 neighbors are expanded (to keep the spike
    tiny); when set, the most-connected neighbors to the seed are expanded first
    so hubs like Kanye West (the route to Paul McCartney) are always included.
    """
    client = client or MBClient()
    acc = EdgeAccumulator()

    # Distance of each discovered artist from the seed.
    distance: Dict[str, int] = {seed_mbid: 0}
    fetched: set = set()

    def ingest(mbid: str) -> None:
        recs = client.fetch_recordings(mbid, max_pages=max_pages)
        acc_local = 0
        for rec in recs:
            credits = parse_credits(rec)
            if len(credits) < 2:
                continue
            acc.add_recording(credits, rec.get("title", ""))
            acc_local += 1
        fetched.add(mbid)
        print(f"  fetched {len(recs)} recordings for {acc.names.get(mbid, mbid)} "
              f"({acc_local} multi-credit)", flush=True)

    # Level 0: seed.
    print(f"[depth 0] seed {seed_mbid}", flush=True)
    ingest(seed_mbid)

    # Neighbors discovered at each level, expanded up to `depth`.
    frontier = [seed_mbid]
    for level in range(1, depth + 1):
        # Collect newly discovered neighbors of the current frontier.
        discovered = []
        for node in frontier:
            for nb in acc.neighbors(node):
                if nb not in distance:
                    distance[nb] = level
                    discovered.append(nb)
        print(f"[depth {level}] discovered {len(discovered)} new artists", flush=True)

        if level == depth:
            # At the final depth we only need the nodes recorded (edges to them
            # already exist); no need to expand their recordings.
            break

        # Expand discovered neighbors to find the next level's edges.
        to_expand = discovered
        if max_degree1 is not None and level == 1:
            # Rank by how strongly connected each neighbor is to the seed's
            # component so hubs (Kanye -> McCartney) are always expanded.
            degree = {m: len(acc.neighbors(m)) for m in discovered}
            to_expand = sorted(discovered, key=lambda m: degree[m], reverse=True)[:max_degree1]
            print(f"[depth {level}] expanding top {len(to_expand)} of "
                  f"{len(discovered)} neighbors", flush=True)

        for i, mbid in enumerate(to_expand, 1):
            if mbid in fetched:
                continue
            print(f"[depth {level}] expand {i}/{len(to_expand)} "
                  f"{acc.names.get(mbid, mbid)}", flush=True)
            ingest(mbid)
        frontier = to_expand

    # Recompute distances over the full accumulated edge set so any node
    # reachable within `depth` (even discovered late) is included.
    reachable = _bfs_reachable(acc, seed_mbid, depth)
    _write_db(acc, reachable, out_path)

    stats = {
        "nodes": len(reachable),
        "edges": sum(1 for a, b in acc.edges() if a in reachable and b in reachable),
        "requests": client.request_count,
        "out": out_path,
    }
    return stats


def _bfs_reachable(acc: EdgeAccumulator, seed: str, depth: int) -> set:
    """Nodes within `depth` hops of seed over the accumulated edge set."""
    dist = {seed: 0}
    q = deque([seed])
    while q:
        node = q.popleft()
        if dist[node] >= depth:
            continue
        for nb in acc.neighbors(node):
            if nb not in dist:
                dist[nb] = dist[node] + 1
                q.append(nb)
    return set(dist.keys())


def _write_db(acc: EdgeAccumulator, reachable: set, out_path: str) -> None:
    """Write the reachable subgraph into a fresh DB in the app's schema."""
    out = Path(out_path)
    if out.exists():
        out.unlink()  # spike DB is disposable; start clean
    db = CollaborationDatabase(str(out))

    for mbid in reachable:
        db.add_artist(mbid, acc.names.get(mbid, mbid))

    for a, b in acc.edges():
        if a not in reachable or b not in reachable:
            continue
        for song in acc.representative_songs(a, b):
            db.add_collaboration(a, b, song)


def main() -> None:
    ap = argparse.ArgumentParser(description="MusicBrainz depth-2 validation spike")
    ap.add_argument("--seed", default=KENDRICK_MBID, help="seed artist MBID")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--out", default="data/mb_spike.db")
    ap.add_argument("--max-pages", type=int, default=60,
                    help="max 100-recording pages per artist")
    ap.add_argument("--max-degree1", type=int, default=None,
                    help="cap on degree-1 neighbors to expand (hubs first)")
    args = ap.parse_args()

    t0 = time.monotonic()
    stats = build_spike(
        seed_mbid=args.seed,
        depth=args.depth,
        out_path=args.out,
        max_pages=args.max_pages,
        max_degree1=args.max_degree1,
    )
    elapsed = time.monotonic() - t0
    print(f"\nDONE in {elapsed:.0f}s — {stats['nodes']} nodes, {stats['edges']} edges, "
          f"{stats['requests']} API requests -> {stats['out']}", flush=True)


if __name__ == "__main__":
    main()
