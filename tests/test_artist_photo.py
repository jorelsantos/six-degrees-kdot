"""Tests for the artist-photo coverage waterfall (plan 010, U1).

All tiers use injected fetch seams — no network. Covers source order, the
EXACT-name Deezer guard (disjoint AND containment rejection), URL validation,
and the NO_PHOTO vs UNAVAILABLE tri-state split.
"""
import requests

import artist_photo
from artist_photo import resolve, NO_PHOTO, UNAVAILABLE

# Valid, allowlisted candidate URLs per source.
WD_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/Kendrick.jpg?width=320"
ADB_URL = "https://r2.theaudiodb.com/images/media/artist/thumb/dom.jpg"
DZ_URL = "https://e-cdns-images.dzcdn.net/images/artist/x/1000x1000.jpg"


def _boom(*args, **kwargs):  # a seam that must not be called
    raise AssertionError("source should not have been consulted")


def _raises(*args, **kwargs):
    raise requests.RequestException("upstream down")


def test_wikidata_hit_short_circuits_later_sources():
    out = resolve(
        [("mbid-k", "Kendrick Lamar")],
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {"mbid-k": WD_URL},
        theaudiodb_fetch=_boom,
        deezer_fetch=_boom,
    )
    assert out == {"mbid-k": WD_URL}


def test_theaudiodb_fills_wikidata_miss_by_mbid():
    out = resolve(
        [("mbid-d", "Dom Kennedy")],
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {},          # Wikidata miss
        theaudiodb_fetch=lambda mbid, t: ADB_URL,    # exact by MBID
        deezer_fetch=_boom,
    )
    assert out == {"mbid-d": ADB_URL}


def test_deezer_exact_name_match_accepted():
    out = resolve(
        [("mbid-lj", "Larry June")],
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {},
        theaudiodb_fetch=lambda mbid, t: None,
        deezer_fetch=lambda name, t: ("Larry June", DZ_URL),
    )
    assert out == {"mbid-lj": DZ_URL}


def test_deezer_disjoint_name_rejected():
    # The probed "C-San" -> "C-kan" mismatch: neither contains the other.
    out = resolve(
        [("mbid-cs", "C-San")],
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {},
        theaudiodb_fetch=lambda mbid, t: None,
        deezer_fetch=lambda name, t: ("C-kan", DZ_URL),
    )
    assert out == {"mbid-cs": NO_PHOTO}  # rejected, all sources consulted


def test_deezer_containment_name_rejected():
    # The stricter case _artist_matches would WRONGLY accept: "June" is a
    # substring of "Larry June", but they are different artists (wrong face).
    out = resolve(
        [("mbid-j", "June")],
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {},
        theaudiodb_fetch=lambda mbid, t: None,
        deezer_fetch=lambda name, t: ("Larry June", DZ_URL),
    )
    assert out == {"mbid-j": NO_PHOTO}


def test_invalid_url_treated_as_miss():
    # A non-https / off-allowlist candidate must never be persisted or served.
    out = resolve(
        [("mbid-x", "Somebody")],
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {"mbid-x": "javascript:alert(1)"},
        theaudiodb_fetch=lambda mbid, t: "http://evil.example.com/x.jpg",
        deezer_fetch=lambda name, t: ("Somebody", "https://tracker.example.net/pixel.gif"),
    )
    assert out == {"mbid-x": NO_PHOTO}  # every candidate rejected, none errored


def test_all_sources_miss_is_no_photo():
    out = resolve(
        [("mbid-z", "Obscure Artist")],
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {},
        theaudiodb_fetch=lambda mbid, t: None,
        deezer_fetch=lambda name, t: None,
    )
    assert out == {"mbid-z": NO_PHOTO}


def test_source_error_is_unavailable_not_none():
    # A transient failure must NOT persist "none" (which would freeze the artist
    # photoless forever) — it comes back UNAVAILABLE so the caller leaves NULL.
    out = resolve(
        [("mbid-e", "Flaky Upstream")],
        budget_s=None,
        wikidata_fetch=_raises,
        theaudiodb_fetch=_raises,
        deezer_fetch=_raises,
    )
    assert out == {"mbid-e": UNAVAILABLE}


def test_partial_error_still_unavailable_when_no_hit():
    # Wikidata errors, later tiers miss cleanly → still UNAVAILABLE (we never
    # definitively ruled out a photo, so it stays retryable).
    out = resolve(
        [("mbid-p", "Partial")],
        budget_s=None,
        wikidata_fetch=_raises,
        theaudiodb_fetch=lambda mbid, t: None,
        deezer_fetch=lambda name, t: None,
    )
    assert out == {"mbid-p": UNAVAILABLE}


def test_budget_exhausted_leaves_unavailable_and_makes_no_calls():
    # budget_s=0 → out of budget before the first tier; nothing is consulted and
    # the artist is left retryable rather than branded no-photo.
    out = resolve(
        [("mbid-b", "Budget")],
        budget_s=0.0,
        wikidata_fetch=_boom,
        theaudiodb_fetch=_boom,
        deezer_fetch=_boom,
    )
    assert out == {"mbid-b": UNAVAILABLE}


def test_mixed_batch_resolves_each_independently():
    artists = [
        ("mbid-a", "Alpha"),   # wikidata hit
        ("mbid-b", "Beta"),    # theaudiodb hit
        ("mbid-c", "Gamma"),   # deezer exact hit
        ("mbid-d", "Delta"),   # all miss
    ]
    out = resolve(
        artists,
        budget_s=None,
        wikidata_fetch=lambda mbids, t: {"mbid-a": WD_URL},
        theaudiodb_fetch=lambda mbid, t: ADB_URL if mbid == "mbid-b" else None,
        deezer_fetch=lambda name, t: ("Gamma", DZ_URL) if name == "Gamma" else None,
    )
    assert out == {
        "mbid-a": WD_URL,
        "mbid-b": ADB_URL,
        "mbid-c": DZ_URL,
        "mbid-d": NO_PHOTO,
    }


def test_validate_url_allows_known_hosts_only():
    assert artist_photo._validate_url(WD_URL) == WD_URL
    assert artist_photo._validate_url(ADB_URL) == ADB_URL
    assert artist_photo._validate_url(DZ_URL) == DZ_URL
    assert artist_photo._validate_url("http://commons.wikimedia.org/x.jpg") is None  # not https
    assert artist_photo._validate_url("https://evil.example.com/x.jpg") is None      # off allowlist
    assert artist_photo._validate_url("data:image/png;base64,AAAA") is None
    assert artist_photo._validate_url(None) is None
