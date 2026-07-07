"""
Plan 008 U1 — Spotify embed scrape feasibility spike (GO/NO-GO gate, KTD6).

Measures, on a real sample of DISPLAYED songs, whether the reverse-engineered
Spotify embed `audioPreview.url` scrape is worth adopting and behaves reliably,
BEFORE wiring it as a preview source. Records: how many displayed songs resolve
to a Spotify track id, and of those, how many embed pages yield a playable
`audioPreview.url` — plus failures/shape issues. Prints a GO/NO-GO.

Safe/minimal posture (KTD7): browser-like UA, conservative pacing, each embed
fetched once. Read-only measurement; no persistence, no full-scale run.

Usage: python3 scripts/spotify_scrape_spike.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

# load .env creds (Spotify id resolution)
for _line in (_ROOT / ".env").read_text().splitlines():
    _line = _line.strip()
    if _line.startswith(("SPOTIFY_CLIENT_ID=", "SPOTIFY_CLIENT_SECRET=")) and "here" not in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

import spotify_enrich as se  # noqa: E402
import preview_coverage_spike as cov  # noqa: E402
from database import CollaborationDatabase  # noqa: E402
from path_finder_sqlite import PathFinder  # noqa: E402

EMBED = "https://open.spotify.com/embed/track/{}"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126 Safari/537.36")
AUDIO_PREVIEW_RE = re.compile(r'"audioPreview"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"')
EMBED_RATE_S = 0.7  # ~1.4 req/s — conservative (KTD7)


def scrape_audio_preview(track_id: str, timeout: float = 8.0):
    """Return (status, url) — status in {'hit','null','no_nextdata','http_err','error'}."""
    try:
        r = requests.get(EMBED.format(track_id), headers={"User-Agent": BROWSER_UA}, timeout=timeout)
        if r.status_code != 200:
            return ("http_err", None)
        html = r.text
        if "__NEXT_DATA__" not in html:
            return ("no_nextdata", None)
        m = AUDIO_PREVIEW_RE.search(html)
        if m and m.group(1) and m.group(1) != "null":
            return ("hit", m.group(1))
        return ("null", None)
    except requests.RequestException:
        return ("error", None)


def main():
    db = CollaborationDatabase(str(_ROOT / "data" / "collaboration_network_mb.db"))
    finder = PathFinder(db)
    kid = db.get_artist_by_name("Kendrick Lamar")["id"]
    songs, n_targets = cov.collect_displayed_songs(db, finder, kid)
    print(f"{n_targets} targets w/ path; {len(songs)} displayed songs sampled\n", flush=True)

    token = se.get_client_token(os.environ["SPOTIFY_CLIENT_ID"], os.environ["SPOTIFY_CLIENT_SECRET"])

    resolved_id = 0
    counts = {"hit": 0, "null": 0, "no_nextdata": 0, "http_err": 0, "error": 0}
    for i, s in enumerate(songs, 1):
        try:
            cands = se.search_track(se._build_query(s["title"], s["artists"]), token)
            tid = se._resolve_track_id(s["title"], s["artists"], cands)
        except Exception:
            tid = se.NO_TRACK_SENTINEL
        if not tid or tid == se.NO_TRACK_SENTINEL:
            continue
        resolved_id += 1
        status, _url = scrape_audio_preview(tid)
        counts[status] += 1
        time.sleep(EMBED_RATE_S)

    n = len(songs)
    print("=" * 60)
    print("SPOTIFY EMBED SCRAPE SPIKE — displayed songs")
    print("=" * 60)
    print(f"displayed songs:              {n}")
    print(f"resolved to a Spotify id:     {resolved_id} ({100*resolved_id/n:.0f}%)")
    print(f"  embed audioPreview HIT:     {counts['hit']}")
    print(f"  embed audioPreview null:    {counts['null']}")
    print(f"  no __NEXT_DATA__:           {counts['no_nextdata']}")
    print(f"  http error (429/403/etc):   {counts['http_err']}")
    print(f"  network error:              {counts['error']}")
    scrape_hit_rate = (100 * counts["hit"] / resolved_id) if resolved_id else 0
    overall = 100 * counts["hit"] / n if n else 0
    print("-" * 60)
    print(f"scrape hit-rate (of id'd):    {scrape_hit_rate:.0f}%")
    print(f"overall preview coverage:     {overall:.0f}% of displayed songs (Spotify tier alone)")
    print("-" * 60)
    # GO/NO-GO: GO if the scrape reliably yields previews for id'd tracks and no rate-limit wall
    blocked = counts["http_err"] + counts["error"]
    if scrape_hit_rate >= 60 and blocked <= max(1, resolved_id * 0.1):
        rec = "GO — scrape is reliable; wire it as the waterfall's first tier (iTunes/Deezer fill gaps)"
    elif scrape_hit_rate >= 30:
        rec = "PARTIAL — scrape works but coverage is modest; iTunes should lead, scrape as a booster"
    else:
        rec = "NO-GO — drop the scrape; iTunes -> Deezer carry the waterfall"
    print(f"RECOMMENDATION: {rec}")
    print("=" * 60)


if __name__ == "__main__":
    main()
