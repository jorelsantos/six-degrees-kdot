"""
U2 + U3 — Build the collaboration graph from the staged MusicBrainz dump.

Reads the tab-separated table files staged by scripts/fetch_musicbrainz_dump.sh
(data/mb_raw/mbdump/), derives co-credit edges under the plan's rules, and
writes a depth-bounded subgraph into a new SQLite DB in the app's schema.

Rules encoded (migration plan):
- KTD2/KTD9: an edge exists ONLY when 2+ artists are co-credited on the same
  recording; that recording is the connecting song. No membership/relationship
  edges. Band/group entities are ordinary nodes.
- KTD7: nodes are keyed on MBID (artist.gid), never display name.
- KTD8: recording versions dedup to a small set of canonical connecting songs.
- KTD10 (added after the U8 spike): a recording counts ONLY if it appears on a
  release with status = Official, and NOT on a release-group whose secondary
  type is Interview/Spokenword/Audiobook. This excludes the bootleg/mashup
  recordings that otherwise manufacture false connections (e.g. the Kanye ×
  Beatles mashup that linked The Beatles to Kendrick).

Design: a streaming, set-based join over the big tables (recording 39M,
track 56M) rather than a full DB load — memory-bounded (~3 GB peak) and fast.
Only a depth-2 BFS from the seed is materialized into the output DB.

CLI:
    python3 src/musicbrainz_ingest.py \
        --mbdump data/mb_raw/mbdump \
        --out data/collaboration_network_mb.db \
        --seed 381086ea-f511-4aba-bdf9-71c753dc5077 --depth 2
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from database import CollaborationDatabase  # noqa: E402

# --- MusicBrainz enum ids (read from the staged lookup tables 2026-07-04) ---
OFFICIAL_STATUS_ID = "1"  # release_status: 1 = Official
# release_group_secondary_type exclusions. 3 = Spokenword, 4 = Interview,
# 5 = Audiobook (non-musical co-credits). 8 = DJ-mix: continuous mixes store
# blended segments as one recording co-crediting both artists (e.g. "Sweet
# Love / wacced out murals" credited "Anita Baker / Kendrick Lamar"), which is
# a mixing artifact, not a real collaboration — so DJ-mix is excluded too.
EXCLUDE_SECONDARY_TYPES = {"3", "4", "5", "8"}

KENDRICK_MBID = "381086ea-f511-4aba-bdf9-71c753dc5077"

# --- column indices (0-based) for the staged TSV files ----------------------
# artist: id, gid, name, ...
A_ID, A_GID, A_NAME = 0, 1, 2
# artist_credit_name: artist_credit, position, artist, name, join_phrase
ACN_CREDIT, ACN_ARTIST, ACN_NAME = 0, 2, 3
# recording: id, gid, name, artist_credit, ...
R_ID, R_NAME, R_CREDIT = 0, 2, 3
# track: id, gid, recording, medium, ...
T_RECORDING, T_MEDIUM = 2, 3
# medium: id, release, ...
M_ID, M_RELEASE = 0, 1
# release: id, gid, name, artist_credit, release_group, status, ...
REL_ID, REL_GROUP, REL_STATUS = 0, 4, 5
# release_group_secondary_type_join: release_group, secondary_type, created
RGSTJ_GROUP, RGSTJ_TYPE = 0, 1


# --- pure edge/dedup logic (lifted from the validated U8 spike, KTD8) --------

_VARIANT_RE = re.compile(
    r"\b(remix|live|instrumental|acoustic|remaster(?:ed)?|edit|radio\s*edit|"
    r"extended|version|mix|demo|snippet|a\s*cappella|acapella|karaoke|"
    r"re-?recorded|reprise|mono|stereo)\b",
    re.IGNORECASE,
)


def is_variant_title(title: str) -> bool:
    return bool(_VARIANT_RE.search(title or ""))


def base_title(title: str) -> str:
    t = title or ""
    t = re.sub(r"[\(\[].*?[\)\]]", " ", t)
    t = re.sub(r"\s-\s.*$", " ", t)
    t = re.sub(r"\b(feat|ft|featuring|with)\b.*", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return " ".join(t.split())


def dedup_songs(titles: Iterable[str], cap: int = 5) -> List[str]:
    """Group titles by base title, keep the cleanest surface form of each,
    canonical/original first, capped."""
    groups: Dict[str, List[str]] = defaultdict(list)
    for t in titles:
        if t:
            groups[base_title(t)].append(t)
    reps = [sorted(v, key=lambda s: (is_variant_title(s), len(s)))[0] for v in groups.values()]
    reps.sort(key=lambda s: (is_variant_title(s), len(s)))
    return reps[:cap]


def _split(line: str) -> List[str]:
    return line.rstrip("\n").split("\t")


class MusicBrainzIngest:
    def __init__(
        self,
        mbdump_dir: str,
        official_status_ids: Optional[Set[str]] = None,
        exclude_secondary: Optional[Set[str]] = None,
    ) -> None:
        self.dir = Path(mbdump_dir)
        self.official_status_ids = official_status_ids or {OFFICIAL_STATUS_ID}
        self.exclude_secondary = (
            EXCLUDE_SECONDARY_TYPES if exclude_secondary is None else exclude_secondary
        )
        # populated during build
        self.artist_name: Dict[str, str] = {}   # artist_id -> display name
        self.artist_gid: Dict[str, str] = {}    # artist_id -> MBID
        self.gid_to_id: Dict[str, str] = {}     # MBID -> artist_id

    def _open(self, table: str):
        return open(self.dir / table, "r", encoding="utf-8", errors="replace")

    def _log(self, msg: str) -> None:
        print(msg, flush=True)

    # --- Phase 1: official recording ids -----------------------------------

    def excluded_release_groups(self) -> Set[str]:
        excluded: Set[str] = set()
        with self._open("release_group_secondary_type_join") as f:
            for line in f:
                c = _split(line)
                if len(c) > RGSTJ_TYPE and c[RGSTJ_TYPE] in self.exclude_secondary:
                    excluded.add(c[RGSTJ_GROUP])
        return excluded

    def official_release_ids(self, excluded_rgs: Set[str]) -> Set[str]:
        out: Set[str] = set()
        with self._open("release") as f:
            for line in f:
                c = _split(line)
                if len(c) <= REL_STATUS:
                    continue
                if c[REL_STATUS] not in self.official_status_ids:
                    continue
                if c[REL_GROUP] in excluded_rgs:
                    continue
                out.add(c[REL_ID])
        return out

    def official_medium_ids(self, official_releases: Set[str]) -> Set[str]:
        out: Set[str] = set()
        with self._open("medium") as f:
            for line in f:
                c = _split(line)
                if len(c) > M_RELEASE and c[M_RELEASE] in official_releases:
                    out.add(c[M_ID])
        return out

    def official_recording_ids(self, official_media: Set[str]) -> Set[str]:
        out: Set[str] = set()
        with self._open("track") as f:
            for line in f:
                c = _split(line)
                if len(c) > T_MEDIUM and c[T_MEDIUM] in official_media:
                    out.add(c[T_RECORDING])
        return out

    # --- Phase 2: credit -> representative official song(s) ----------------

    def credit_songs(self, official_recordings: Set[str]) -> Dict[str, List[str]]:
        """artist_credit id -> up to a few canonical song titles from its
        official recordings. Credits with no official recording are absent."""
        raw: Dict[str, List[str]] = defaultdict(list)
        with self._open("recording") as f:
            for line in f:
                c = _split(line)
                if len(c) <= R_CREDIT:
                    continue
                if c[R_ID] in official_recordings:
                    # keep a bounded number of raw titles per credit; dedup later
                    lst = raw[c[R_CREDIT]]
                    if len(lst) < 40:
                        lst.append(c[R_NAME])
        return {cid: dedup_songs(titles) for cid, titles in raw.items()}

    # --- Phase 3: artist <-> credit indices (official credits only) --------

    def credit_indices(
        self, official_credits: Set[str]
    ) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        """Returns (credit_to_artists, artist_to_credits) restricted to official
        credits that have 2+ distinct artists."""
        credit_to_artists: Dict[str, List[str]] = defaultdict(list)
        with self._open("artist_credit_name") as f:
            for line in f:
                c = _split(line)
                if len(c) <= ACN_ARTIST:
                    continue
                cid = c[ACN_CREDIT]
                if cid not in official_credits:
                    continue
                aid = c[ACN_ARTIST]
                # Skip credits referencing an artist absent from the artist
                # table (defensive; keeps the run from creating id-only nodes).
                if self.artist_name and aid not in self.artist_name:
                    continue
                if aid not in credit_to_artists[cid]:
                    credit_to_artists[cid].append(aid)
        # drop single-artist credits (no edge), build reverse index
        artist_to_credits: Dict[str, List[str]] = defaultdict(list)
        multi = {}
        for cid, artists in credit_to_artists.items():
            if len(artists) >= 2:
                multi[cid] = artists
                for aid in artists:
                    artist_to_credits[aid].append(cid)
        return multi, artist_to_credits

    def load_artists(self, needed: Optional[Set[str]] = None) -> None:
        """Load artist id -> (gid, name). If `needed` given, only keep those ids
        (plus always build gid_to_id for seed lookup)."""
        with self._open("artist") as f:
            for line in f:
                c = _split(line)
                if len(c) <= A_NAME:
                    continue
                aid = c[A_ID]
                self.gid_to_id[c[A_GID]] = aid
                if needed is None or aid in needed:
                    self.artist_name[aid] = c[A_NAME]
                    self.artist_gid[aid] = c[A_GID]

    # --- Phase 4/5: BFS + write --------------------------------------------

    def build(self, seed_mbid: str, depth: int, out_path: str) -> Dict:
        t0 = time.monotonic()
        self._log("[1/6] excluded release-groups (Interview/Spokenword/Audiobook) ...")
        excluded_rgs = self.excluded_release_groups()
        self._log(f"      {len(excluded_rgs):,} release-groups excluded")

        self._log("[2/6] official releases -> media -> recordings ...")
        off_rel = self.official_release_ids(excluded_rgs)
        self._log(f"      {len(off_rel):,} official releases")
        off_med = self.official_medium_ids(off_rel)
        del off_rel
        self._log(f"      {len(off_med):,} official media")
        off_rec = self.official_recording_ids(off_med)
        del off_med
        self._log(f"      {len(off_rec):,} official recordings")

        self._log("[3/6] credit -> canonical official song(s) ...")
        credit_to_songs = self.credit_songs(off_rec)
        del off_rec
        official_credits = set(credit_to_songs.keys())
        self._log(f"      {len(official_credits):,} credits with an official recording")

        self._log("[4/6] loading artist names + resolving seed ...")
        # Load all artists (2.9M, cheap) so the seed and every reachable node
        # resolves, and so credit_indices can skip dangling artist references.
        self.load_artists()
        seed_id = self.gid_to_id.get(seed_mbid)
        if not seed_id:
            raise SystemExit(f"Seed MBID {seed_mbid} not found in artist table")
        self._log(f"      seed {seed_mbid} -> artist id {seed_id} "
                  f"({self.artist_name.get(seed_id)})")

        self._log("[5/6] artist<->credit indices (multi-artist official credits) ...")
        credit_to_artists, artist_to_credits = self.credit_indices(official_credits)
        self._log(f"      {len(credit_to_artists):,} co-credit credits")

        self._log(f"[6/6] BFS depth-{depth} + writing {out_path} ...")
        edges = self._bfs(seed_id, depth, credit_to_artists, artist_to_credits, credit_to_songs)
        stats = self._write(edges, out_path)
        stats["seconds"] = round(time.monotonic() - t0, 1)
        return stats

    def _bfs(self, seed_id, depth, credit_to_artists, artist_to_credits, credit_to_songs):
        """BFS over the artist co-credit graph to `depth`; accumulate edges with
        their connecting songs AND the full credited lineup per song.
        Returns {sorted(a,b): {song_title: set(all credited artist_ids)}}."""
        edges: Dict[Tuple[str, str], Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        dist = {seed_id: 0}
        q = deque([seed_id])
        while q:
            a = q.popleft()
            if dist[a] >= depth:
                continue
            for cid in artist_to_credits.get(a, []):
                lineup = credit_to_artists.get(cid, [])  # all artists on this recording
                songs = credit_to_songs.get(cid, [])
                for b in lineup:
                    if b == a:
                        continue
                    key = (a, b) if a <= b else (b, a)
                    title_map = edges[key]
                    for title in songs:
                        title_map[title].update(lineup)
                    if b not in dist:
                        dist[b] = dist[a] + 1
                        q.append(b)
        # keep only edges whose both endpoints are within the reachable set
        reachable = set(dist.keys())
        return {k: v for k, v in edges.items() if k[0] in reachable and k[1] in reachable}

    def _write(self, edges: Dict[Tuple[str, str], Dict[str, Set[str]]], out_path: str) -> Dict:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        db = CollaborationDatabase(str(out))

        nodes: Set[str] = set()
        for a, b in edges:
            nodes.add(a)
            nodes.add(b)
        for aid in nodes:
            # node id = MBID (KTD7); display name from artist table
            db.add_artist(self.artist_gid.get(aid, aid), self.artist_name.get(aid, aid))
        for (a, b), title_map in edges.items():
            ga, gb = self.artist_gid.get(a, a), self.artist_gid.get(b, b)
            for song in dedup_songs(list(title_map.keys())):
                lineup_ids = title_map.get(song, set())
                lineup_names = sorted(self.artist_name.get(i, i) for i in lineup_ids)
                db.add_collaboration(ga, gb, song, collaborators=lineup_names)

        s = db.get_stats()
        s["out"] = out_path
        return s


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the MusicBrainz collaboration graph")
    ap.add_argument("--mbdump", default="data/mb_raw/mbdump", help="staged dump dir")
    ap.add_argument("--out", default="data/collaboration_network_mb.db")
    ap.add_argument("--seed", default=KENDRICK_MBID)
    ap.add_argument("--depth", type=int, default=2)
    args = ap.parse_args()

    ingest = MusicBrainzIngest(args.mbdump)
    stats = ingest.build(args.seed, args.depth, args.out)
    print(f"\nDONE in {stats['seconds']}s — {stats['total_artists']:,} artists, "
          f"{stats['total_collaborations']:,} collaborations, "
          f"{stats['total_songs']:,} songs -> {stats['out']}")


if __name__ == "__main__":
    main()
