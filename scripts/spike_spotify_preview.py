"""
U4 — Spotify preview SPIKE (experiment only, NOT production code).

Question: in July 2026, can we get a usable 30s Spotify preview cleanly enough
to adopt over the current iTunes/Deezer path? Per the plan (KTD4) this is a
timeboxed experiment with a HARD safety budget so it cannot become a crawl (the
failure mode that killed the retired Spotify crawler).

SAFETY BUDGET (enforced below, non-negotiable):
  - <= 20 total HTTP requests, tracked by a hard counter that aborts the run.
  - Abort immediately on the first 429; print Retry-After; never retry-loop.
  - NO iteration over the artists/collaborations tables — a fixed handful of
    hand-picked tracks only.
  - Client-credentials app token only; never a personal-account login.

This script makes real requests with SPOTIFY_CLIENT_ID/SECRET. It is throwaway:
if the spike is a no-go, delete it; if it's a go, adoption is a separate unit.
"""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
OEMBED_URL = "https://open.spotify.com/oembed"
TIMEOUT = 6.0
REQUEST_BUDGET = 20

# Fixed, hand-picked tracks — NOT drawn from the graph. Kept tiny on purpose.
TEST_TRACKS = [
    ("No More Parties in L.A.", "Kanye West"),
    ("Snooze", "SZA"),
    ("HUMBLE.", "Kendrick Lamar"),
    ("Bad and Boujee", "Migos"),
]


class Budget:
    """Hard request budget — makes the spike structurally incapable of crawling."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def spend(self, label: str):
        self.used += 1
        if self.used > self.limit:
            raise SystemExit(f"ABORT: request budget of {self.limit} exceeded (at '{label}').")
        print(f"  [req {self.used}/{self.limit}] {label}")


def _get(budget: Budget, label: str, url: str, **kwargs) -> requests.Response:
    budget.spend(label)
    resp = requests.get(url, timeout=TIMEOUT, **kwargs)
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After", "?")
        raise SystemExit(f"ABORT: 429 rate-limited (Retry-After={retry}s). Stopping per safety budget.")
    return resp


def get_token(budget: Budget, cid: str, secret: str) -> str:
    budget.spend("POST token (client-credentials)")
    resp = requests.post(
        TOKEN_URL, timeout=TIMEOUT,
        data={"grant_type": "client_credentials"},
        auth=(cid, secret),
    )
    if resp.status_code == 429:
        raise SystemExit("ABORT: 429 on token request. Stopping.")
    resp.raise_for_status()
    return resp.json()["access_token"]


def main() -> int:
    load_dotenv()
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "")
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not cid or not secret or "here" in cid:
        print("error: SPOTIFY_CLIENT_ID/SECRET not configured in .env", file=sys.stderr)
        return 1

    budget = Budget(REQUEST_BUDGET)
    print(f"Spotify preview spike — hard budget {REQUEST_BUDGET} requests, "
          f"{len(TEST_TRACKS)} fixed test tracks.\n")

    print("1) Client-credentials token flow:")
    token = get_token(budget, cid, secret)
    print("   -> token acquired (app-level, no user login).\n")
    headers = {"Authorization": f"Bearer {token}"}

    print("2) /v1/search — does the response still include a usable preview_url?")
    preview_hits = 0
    track_id_hits = 0
    for title, artist in TEST_TRACKS:
        resp = _get(
            budget, f"search {title!r}", SEARCH_URL,
            headers=headers,
            params={"q": f"track:{title} artist:{artist}", "type": "track", "limit": 1},
        )
        resp.raise_for_status()
        items = resp.json().get("tracks", {}).get("items", [])
        if not items:
            print(f"     {title!r}: no result")
            continue
        t = items[0]
        pv = t.get("preview_url")
        tid = t.get("id")
        if tid:
            track_id_hits += 1
        if pv:
            preview_hits += 1
        print(f"     {title!r}: track_id={'yes' if tid else 'NO'}  preview_url={'YES' if pv else 'null'}")

    print("\n3) oEmbed (no auth) — is the embed-player route available as a fallback?")
    oembed_ok = False
    try:
        resp = _get(
            budget, "oembed sample", OEMBED_URL,
            params={"url": "https://open.spotify.com/track/4iZ4pt7kvcaH6Yo8UoZ4s2"},
        )
        oembed_ok = resp.status_code == 200 and "iframe" in resp.text
        print(f"     oEmbed player available: {oembed_ok}")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — spike, report and move on
        print(f"     oEmbed check failed: {e}")

    print("\n" + "=" * 60)
    print("FINDINGS")
    print(f"  requests used:          {budget.used}/{budget.limit}")
    print(f"  tracks with track_id:   {track_id_hits}/{len(TEST_TRACKS)}")
    print(f"  tracks with preview_url:{preview_hits}/{len(TEST_TRACKS)}")
    print(f"  embed (oEmbed) route:   {'available' if oembed_ok else 'unavailable'}")
    print("=" * 60)
    print("\nInterpretation left to the go/no-go note (see docs). Reminder:")
    print("  - preview_url via search = live per-query calls at runtime -> volume risk.")
    print("  - embed route = resolve track_id once at build, player loads client-side.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
