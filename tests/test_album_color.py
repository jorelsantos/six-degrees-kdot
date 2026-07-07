"""Tests for server-side dominant-color extraction (plan 009, U1)."""
from io import BytesIO

import album_color
from PIL import Image


def _png(color):
    buf = BytesIO()
    Image.new("RGB", (24, 24), color).save(buf, format="PNG")
    return buf.getvalue()


def setup_function(_):
    album_color.clear_cache()


def test_dominant_color_of_solid_red_is_reddish():
    c = album_color.dominant_color("u-red", fetch=lambda u, t: _png((220, 20, 20)))
    assert c and c.startswith("#")
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    assert r > 150 and g < 100 and b < 100


def test_none_url_returns_none():
    assert album_color.dominant_color(None) is None


def test_fetch_none_returns_none():
    assert album_color.dominant_color("u", fetch=lambda u, t: None) is None


def test_fetch_error_returns_none_no_raise():
    import requests

    def boom(u, t):
        raise requests.RequestException("down")

    assert album_color.dominant_color("u", fetch=boom) is None


def test_corrupt_bytes_returns_none_no_raise():
    assert album_color.dominant_color("u", fetch=lambda u, t: b"not-an-image") is None


def test_caches_per_url():
    calls = {"n": 0}

    def f(u, t):
        calls["n"] += 1
        return _png((10, 10, 200))

    album_color.dominant_color("k", fetch=f)
    album_color.dominant_color("k", fetch=f)
    assert calls["n"] == 1
