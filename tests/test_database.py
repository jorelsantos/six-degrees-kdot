"""
Unit tests for the artist-alias layer on CollaborationDatabase (2026-07-05).

Aliases let a search by any known name resolve to the canonical node
("Kanye West" -> "Ye"). These tests isolate the DB behavior from the dump.
"""

from database import CollaborationDatabase


def _db(tmp_path):
    return CollaborationDatabase(str(tmp_path / "aliases.db"))


def test_alias_exact_lookup_resolves_to_canonical(tmp_path):
    db = _db(tmp_path)
    db.add_artist("mbid-ye", "Ye")
    db.add_artist_alias("mbid-ye", "Kanye West")

    # Canonical name still works, and the alias resolves to the same node.
    assert db.get_artist_by_name("Ye")["id"] == "mbid-ye"
    hit = db.get_artist_by_name("Kanye West")
    assert hit is not None and hit["id"] == "mbid-ye"
    assert hit["name"] == "Ye"  # display stays canonical


def test_alias_lookup_is_case_insensitive(tmp_path):
    db = _db(tmp_path)
    db.add_artist("mbid-ye", "Ye")
    db.add_artist_alias("mbid-ye", "Kanye West")
    assert db.get_artist_by_name("kanye west")["id"] == "mbid-ye"


def test_search_dedups_to_one_canonical_row(tmp_path):
    db = _db(tmp_path)
    db.add_artist("mbid-ye", "Ye")
    db.add_artist_aliases("mbid-ye", ["Kanye West", "Yeezy"])
    # Matching by alias returns the canonical artist exactly once (not per alias).
    hits = db.search_artists("Kanye")
    assert [h["id"] for h in hits] == ["mbid-ye"]
    # A query that hits both name and an alias still yields a single row.
    hits2 = db.search_artists("Ye")
    assert [h["id"] for h in hits2].count("mbid-ye") == 1


def test_shared_alias_prefers_more_popular(tmp_path):
    db = _db(tmp_path)
    db.add_artist("mbid-a", "Artist A", popularity=10)
    db.add_artist("mbid-b", "Artist B", popularity=90)
    # Both claim the same alias string; exact lookup picks the more popular one.
    db.add_artist_alias("mbid-a", "The Kid")
    db.add_artist_alias("mbid-b", "The Kid")
    assert db.get_artist_by_name("The Kid")["id"] == "mbid-b"


def test_blank_alias_ignored(tmp_path):
    db = _db(tmp_path)
    db.add_artist("mbid-ye", "Ye")
    db.add_artist_alias("mbid-ye", "   ")
    db.add_artist_aliases("mbid-ye", ["", None])
    # No alias rows created; a blank query doesn't resolve to the artist.
    assert db.get_artist_by_name("Kanye West") is None


def test_no_aliases_behaves_like_before(tmp_path):
    """A DB with no aliases (the legacy Spotify build) still loads and searches
    exactly as before — the alias table just stays empty."""
    db = _db(tmp_path)
    db.add_artist("id-1", "Drake")
    assert db.get_artist_by_name("Drake")["id"] == "id-1"
    assert db.get_artist_by_name("Aubrey Graham") is None
    assert [h["id"] for h in db.search_artists("Dra")] == ["id-1"]
