"""Tests for the preview waterfall resolver (plan 008, U2)."""
import preview_fetcher
import preview_resolver
from preview_resolver import resolve_preview, apple_search_url


def _itunes_hit(title, artists, timeout):
    return preview_fetcher.Preview(
        preview_url="https://audio-ssl.itunes.apple.com/x.m4a",
        provider="itunes", store_url="https://music.apple.com/x",
        matched_title=title, matched_artist=(artists[0] if artists else None),
    )


def _deezer_hit(title, artists, timeout):
    return preview_fetcher.Preview(
        preview_url="https://cdns-preview.deezer.com/x.mp3",
        provider="deezer", store_url="https://deezer.com/x",
        matched_title=title, matched_artist=(artists[0] if artists else None),
    )


def _miss(title, artists, timeout):
    return None


def test_spotify_tier_wins_when_scrape_hits():
    r = resolve_preview(
        "luther", ["Kendrick Lamar", "SZA"], spotify_track_id="tid1",
        scrape=lambda tid: {"audio_url": "https://p.scdn.co/mp3-preview/x", "artwork_url": "https://i.scdn.co/image/y"},
        itunes=_itunes_hit, deezer=_deezer_hit,
    )
    assert r.source == "spotify"
    assert r.audio_url == "https://p.scdn.co/mp3-preview/x"
    assert r.artwork_url == "https://i.scdn.co/image/y"
    assert r.store_url == "https://open.spotify.com/track/tid1"


def test_falls_through_to_itunes_when_no_track_id():
    r = resolve_preview("Cruel", ["Jay Rock"], spotify_track_id=None,
                        scrape=lambda tid: None, itunes=_itunes_hit, deezer=_deezer_hit)
    assert r.source == "itunes"
    assert r.audio_url.endswith(".m4a")


def test_falls_through_to_itunes_when_scrape_misses():
    r = resolve_preview("x", ["a"], spotify_track_id="tid",
                        scrape=lambda tid: None, itunes=_itunes_hit, deezer=_deezer_hit)
    assert r.source == "itunes"


def test_deezer_last_when_spotify_and_itunes_miss():
    r = resolve_preview("x", ["a"], spotify_track_id="tid",
                        scrape=lambda tid: None, itunes=_miss, deezer=_deezer_hit)
    assert r.source == "deezer"


def test_all_miss_returns_none():
    r = resolve_preview("x", ["a"], spotify_track_id="tid",
                        scrape=lambda tid: None, itunes=_miss, deezer=_miss)
    assert r is None


def test_sentinel_track_id_skips_spotify_tier():
    r = resolve_preview("x", ["a"], spotify_track_id="none",
                        scrape=lambda tid: (_ for _ in ()).throw(AssertionError("must not scrape sentinel")),
                        itunes=_itunes_hit, deezer=_deezer_hit)
    assert r.source == "itunes"


def test_itunes_network_error_falls_through_no_raise():
    import requests

    def boom(title, artists, timeout):
        raise requests.RequestException("down")

    r = resolve_preview("x", ["a"], spotify_track_id=None,
                        scrape=lambda tid: None, itunes=boom, deezer=_deezer_hit)
    assert r.source == "deezer"


def test_apple_search_url_encodes_term():
    url = apple_search_url("Real Friends", "Kanye West")
    assert url.startswith("https://music.apple.com/us/search?term=")
    assert "Real" in url and "Kanye" in url
