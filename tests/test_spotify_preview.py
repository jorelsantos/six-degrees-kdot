"""Tests for the Spotify embed preview scraper (plan 008, U1)."""
import spotify_preview


_HTML_HIT = (
    '<html><script id="__NEXT_DATA__" type="application/json">'
    '{"props":{"pageProps":{"state":{"data":{"entity":'
    '{"audioPreview":{"url":"https://p.scdn.co/mp3-preview/abc123"},'
    '"coverArt":{"sources":[{"url":"https://i.scdn.co/image/deadbeef"}]}}}}}}}'
    '</script></html>'
)
_HTML_NULL = (
    '<html><script id="__NEXT_DATA__" type="application/json">'
    '{"entity":{"audioPreview":{"url":null}}}</script></html>'
)
_HTML_NO_NEXTDATA = "<html><body>nope</body></html>"


def setup_function(_):
    spotify_preview.clear_cache()


def test_scrape_hit_returns_audio_and_artwork():
    r = spotify_preview.scrape_preview("t1", fetch=lambda tid, to: _HTML_HIT)
    assert r["audio_url"] == "https://p.scdn.co/mp3-preview/abc123"
    assert r["artwork_url"] == "https://i.scdn.co/image/deadbeef"


def test_scrape_null_preview_returns_none():
    assert spotify_preview.scrape_preview("t2", fetch=lambda tid, to: _HTML_NULL) is None


def test_scrape_missing_nextdata_returns_none():
    assert spotify_preview.scrape_preview("t3", fetch=lambda tid, to: _HTML_NO_NEXTDATA) is None


def test_scrape_none_html_returns_none():
    assert spotify_preview.scrape_preview("t4", fetch=lambda tid, to: None) is None


def test_scrape_empty_track_id_returns_none():
    assert spotify_preview.scrape_preview("") is None


def test_scrape_network_error_returns_none_no_raise():
    import requests

    def boom(tid, to):
        raise requests.RequestException("down")

    assert spotify_preview.scrape_preview("t5", fetch=boom) is None


def test_scrape_caches_per_track():
    calls = {"n": 0}

    def counting(tid, to):
        calls["n"] += 1
        return _HTML_HIT

    spotify_preview.scrape_preview("t6", fetch=counting)
    spotify_preview.scrape_preview("t6", fetch=counting)
    assert calls["n"] == 1
