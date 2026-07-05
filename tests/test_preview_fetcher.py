"""
Offline unit tests for the iTunes+Deezer preview fetcher (U4).

Network is stubbed via monkeypatching requests.get, so these run without
hitting Apple/Deezer.
"""

import requests

import preview_fetcher as pf


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _itunes_payload(tracks):
    return {"resultCount": len(tracks), "results": tracks}


def _deezer_payload(tracks):
    return {"data": tracks}


def setup_function(_):
    pf.clear_cache()


def test_itunes_hit_returns_itunes_preview(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        assert "itunes.apple.com" in url
        return _FakeResp(_itunes_payload([
            {"trackName": "HUMBLE.", "artistName": "Kendrick Lamar",
             "previewUrl": "https://itunes/preview.m4a",
             "trackViewUrl": "https://music.apple.com/humble"},
        ]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    pv = pf.get_preview("HUMBLE.", ["Kendrick Lamar"])
    assert pv is not None
    assert pv.provider == "itunes"
    assert pv.preview_url == "https://itunes/preview.m4a"
    assert pv.store_url == "https://music.apple.com/humble"


def test_falls_back_to_deezer_when_itunes_empty(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        if "itunes.apple.com" in url:
            return _FakeResp(_itunes_payload([]))  # no iTunes match
        return _FakeResp(_deezer_payload([
            {"title": "All Day", "artist": {"name": "Kanye West"},
             "preview": "https://deezer/preview.mp3", "link": "https://deezer/all-day"},
        ]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    pv = pf.get_preview("All Day", ["Kanye West", "Paul McCartney"])
    assert pv is not None
    assert pv.provider == "deezer"
    assert pv.preview_url == "https://deezer/preview.mp3"


def test_no_match_anywhere_returns_none(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        if "itunes.apple.com" in url:
            return _FakeResp(_itunes_payload([]))
        return _FakeResp(_deezer_payload([]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    assert pf.get_preview("Nonexistent Obscure Track", ["Nobody"]) is None


def test_itunes_error_falls_through_to_deezer(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        if "itunes.apple.com" in url:
            raise requests.ConnectionError("boom")
        return _FakeResp(_deezer_payload([
            {"title": "Song", "artist": {"name": "Danny Brown"},
             "preview": "https://deezer/x.mp3", "link": "https://deezer/x"},
        ]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    pv = pf.get_preview("Song", ["Danny Brown"])
    assert pv is not None and pv.provider == "deezer"


def test_both_providers_error_returns_none(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        raise requests.Timeout("slow")
    monkeypatch.setattr(pf.requests, "get", fake_get)

    assert pf.get_preview("Song", ["A"]) is None


def test_prefers_title_and_artist_match_over_other_results(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        return _FakeResp(_itunes_payload([
            {"trackName": "Wrong Song", "artistName": "X",
             "previewUrl": "https://itunes/wrong.m4a", "trackViewUrl": "u1"},
            {"trackName": "Alright", "artistName": "Kendrick Lamar",
             "previewUrl": "https://itunes/right.m4a", "trackViewUrl": "u2"},
        ]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    pv = pf.get_preview("Alright", ["Kendrick Lamar"])
    assert pv.preview_url == "https://itunes/right.m4a"


def test_result_is_cached(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls["n"] += 1
        return _FakeResp(_itunes_payload([
            {"trackName": "Some Song", "artistName": "Some Artist",
             "previewUrl": "https://itunes/s.m4a", "trackViewUrl": "u"},
        ]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    a = pf.get_preview("Some Song", ["Some Artist"])
    b = pf.get_preview("Some Song", ["Some Artist"])
    assert a is not None and calls["n"] == 1  # second lookup served from cache


# --- regression: the "Really Doe -> JP Saxe" wrong-preview bug --------------

def test_no_title_match_returns_none_not_first_result(monkeypatch):
    # iTunes returns unrelated tracks (as it does for "Really Doe" + features):
    # none titled like the query -> must return None, NOT the first result.
    def fake_get(url, params=None, timeout=None, headers=None):
        payload = [
            {"trackName": "If the World Was Ending (feat. Julia Michaels)",
             "artistName": "JP Saxe", "previewUrl": "https://itunes/jp.m4a", "trackViewUrl": "u1"},
            {"trackName": "Cry", "artistName": "Benson Boone",
             "previewUrl": "https://itunes/cry.m4a", "trackViewUrl": "u2"},
        ]
        if "itunes.apple.com" in url:
            return _FakeResp(_itunes_payload(payload))
        return _FakeResp(_deezer_payload([]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    assert pf.get_preview("Really Doe", ["Earl Sweatshirt", "Kendrick Lamar"]) is None


def test_title_match_but_wrong_artist_returns_none(monkeypatch):
    # A same-titled song by an unrelated artist (Ice Cube's "Really Doe") must
    # NOT be served for an Earl Sweatshirt / Kendrick connection.
    def fake_get(url, params=None, timeout=None, headers=None):
        if "itunes.apple.com" in url:
            return _FakeResp(_itunes_payload([
                {"trackName": "Really Doe", "artistName": "Ice Cube",
                 "previewUrl": "https://itunes/icecube.m4a", "trackViewUrl": "u1"},
            ]))
        return _FakeResp(_deezer_payload([]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    assert pf.get_preview("Really Doe", ["Earl Sweatshirt", "Kendrick Lamar"]) is None


def test_title_and_artist_both_match_is_accepted(monkeypatch):
    # The real good case: "All the Stars" by "Kendrick Lamar, SZA".
    def fake_get(url, params=None, timeout=None, headers=None):
        return _FakeResp(_itunes_payload([
            {"trackName": "All The Stars", "artistName": "Kendrick Lamar, SZA",
             "previewUrl": "https://itunes/stars.m4a", "trackViewUrl": "u1"},
        ]))
    monkeypatch.setattr(pf.requests, "get", fake_get)

    pv = pf.get_preview("All the Stars", ["Kendrick Lamar", "SZA"])
    assert pv is not None and pv.preview_url == "https://itunes/stars.m4a"
