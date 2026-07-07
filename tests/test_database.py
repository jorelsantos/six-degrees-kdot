"""
Unit tests for the artist-alias layer on CollaborationDatabase (2026-07-05).

Aliases let a search by any known name resolve to the canonical node
("Kanye West" -> "Ye"). These tests isolate the DB behavior from the dump.
"""

import pytest

from database import (
    CollaborationDatabase,
    CROSS_TIER_OVERRIDE_FACTOR,
    FUZZY_MIN_RESULTS,
    PHOTO_NONE_SENTINEL,
    disambiguate_labels,
    fold_name,
)


def _db(tmp_path):
    return CollaborationDatabase(str(tmp_path / "aliases.db"))


# --- artists.photo_url persistence (plan 010, U1 / KTD2) ---------------------

def test_photo_url_migration_and_roundtrip(tmp_path):
    db = _db(tmp_path)
    db.add_artist("a1", "Kendrick Lamar")
    db.add_artist("a2", "Dom Kennedy")
    db.add_artist("a3", "Flaky Upstream")

    # Fresh column: every artist is unchecked (NULL).
    assert db.get_photo_urls(["a1", "a2", "a3"]) == {"a1": None, "a2": None, "a3": None}

    url = "https://commons.wikimedia.org/wiki/Special:FilePath/K.jpg?width=320"
    db.set_photo_url("a1", url)                    # resolved URL
    db.set_photo_url("a2", PHOTO_NONE_SENTINEL)    # full waterfall missed
    # a3 stays NULL (a transient failure — left retryable)

    got = db.get_photo_urls(["a1", "a2", "a3"])
    assert got["a1"] == url
    assert got["a2"] == PHOTO_NONE_SENTINEL
    assert got["a3"] is None


def test_photo_url_bulk_set(tmp_path):
    db = _db(tmp_path)
    db.add_artist("a1", "Alpha")
    db.add_artist("a2", "Beta")
    db.set_photo_urls_bulk([
        ("a1", "https://r2.theaudiodb.com/x.jpg"),
        ("a2", PHOTO_NONE_SENTINEL),
    ])
    got = db.get_photo_urls(["a1", "a2"])
    assert got["a1"] == "https://r2.theaudiodb.com/x.jpg"
    assert got["a2"] == PHOTO_NONE_SENTINEL


def test_get_photo_urls_empty_and_unknown_ids(tmp_path):
    db = _db(tmp_path)
    db.add_artist("a1", "Alpha")
    assert db.get_photo_urls([]) == {}
    # Unknown ids simply don't appear in the result.
    assert db.get_photo_urls(["nope"]) == {}


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


# --- U2: search ranking ----------------------------------------------------

def test_search_ranks_by_popularity(tmp_path):
    """The headline bug: "Mariah" must surface Mariah Carey first, not the
    alphabetically-first obscure Mariah."""
    db = _db(tmp_path)
    db.add_artist("carey", "Mariah Carey", popularity=3_430_494)
    db.add_artist("adigun", "Mariah Adigun", popularity=1)
    db.add_artist("scientist", "Mariah the Scientist", popularity=25_315)
    names = [h["name"] for h in db.search_artists("Mariah")]
    assert names[:3] == ["Mariah Carey", "Mariah the Scientist", "Mariah Adigun"]


def test_search_prefix_boost_beats_higher_popularity_midstring(tmp_path):
    """A prefix match ranks above a mid-string match even when the mid-string
    artist is more popular — "Dra" should lead with Drake, not Sandra Draper."""
    db = _db(tmp_path)
    db.add_artist("drake", "Drake", popularity=50)
    db.add_artist("sandra", "Sandra Draper", popularity=999)
    assert db.search_artists("Dra")[0]["name"] == "Drake"


def test_exact_and_prefix_share_a_tier_popularity_decides(tmp_path):
    """Exact match does NOT get its own tier above prefix — otherwise an obscure
    artist named exactly "Mariah" would float above Mariah Carey. Within the
    prefix tier, popularity decides."""
    db = _db(tmp_path)
    db.add_artist("mariah", "Mariah", popularity=1)          # exact, obscure
    db.add_artist("carey", "Mariah Carey", popularity=3_430_494)  # prefix, popular
    assert db.search_artists("Mariah")[0]["name"] == "Mariah Carey"


def test_search_degree_breaks_popularity_ties(tmp_path):
    """Equal popularity -> more-collaborative artist wins, ahead of name order."""
    db = _db(tmp_path)
    db.add_artist("z", "Nova Z", popularity=10)
    db.add_artist("a", "Nova A", popularity=10)
    db.add_artist("c", "C")
    db.add_collaboration("z", "c", "Song")  # Nova Z degree 1; Nova A degree 0
    db.refresh_degrees()  # degree is a precomputed column now
    names = [h["name"] for h in db.search_artists("Nova")]
    # Degree beats the alphabetical name tiebreak (else "Nova A" would lead).
    assert names == ["Nova Z", "Nova A"]


# --- U3: typo-tolerant fuzzy fallback --------------------------------------

def test_fuzzy_recovers_from_typo(tmp_path):
    """Covers R3. A misspelled query with no substring match still surfaces the
    intended artist."""
    db = _db(tmp_path)
    db.add_artist("mts", "Mariah the Scientist", popularity=100)
    db.add_artist("drake", "Drake", popularity=100)
    # "Maria the scientist" (missing 'h') has no LIKE match -> fuzzy fallback.
    names = [h["name"] for h in db.search_artists("Maria the scientist")]
    assert "Mariah the Scientist" in names


def test_fuzzy_not_triggered_when_sql_is_rich(tmp_path, monkeypatch):
    """A well-matched query stays on the fast SQL path — fuzzy never runs."""
    db = _db(tmp_path)
    for i in range(5):
        db.add_artist(f"lil{i}", f"Lil Artist {i}", popularity=i)

    called = {"n": 0}
    real = db._fuzzy_search

    def spy(query, limit):
        called["n"] += 1
        return real(query, limit)

    monkeypatch.setattr(db, "_fuzzy_search", spy)
    hits = db.search_artists("Lil")           # 5 SQL hits >= FUZZY_MIN_RESULTS
    assert len(hits) >= FUZZY_MIN_RESULTS
    assert called["n"] == 0                   # fuzzy path skipped


def test_fuzzy_gibberish_returns_nothing(tmp_path):
    db = _db(tmp_path)
    db.add_artist("mts", "Mariah the Scientist", popularity=100)
    assert db.search_artists("zxqwvk") == []  # below score cutoff -> no junk


def test_fuzzy_rows_have_candidate_shape(tmp_path):
    """All candidates — SQL or fuzzy path — carry the full candidate shape
    (id/name/popularity/genres + degree for U4 labels + tier)."""
    db = _db(tmp_path)
    db.add_artist("mts", "Mariah the Scientist", popularity=100, genres=["r&b"])
    hit = db.search_artists("Maria the scientist")[0]
    assert {"id", "name", "popularity", "genres", "degree", "tier"} <= set(hit.keys())
    assert hit["genres"] == ["r&b"]
    assert hit["tier"] == 2  # fuzzy path


# --- Plan 2026-07-06-002: unified resolution pipeline ------------------------

def test_fold_name_class_differentiated():
    """Dots/apostrophes DELETE; separators become SPACES. The asymmetry is
    load-bearing: a uniform rule fails one vector family or the other."""
    assert fold_name("The Notorious B.I.G.") == "the notorious big"   # dots delete
    assert fold_name("JAY‐Z") == "jay z"                          # U+2010 hyphen -> space
    assert fold_name("Tyler, The Creator") == "tyler the creator"      # comma -> space
    assert fold_name("Beyoncé") == "beyonce"                      # accent strip
    assert fold_name("Lil’ Flip") == "lil flip"                   # apostrophe deletes
    assert fold_name("B.I.G.") != "b i g"                              # the failure mode, pinned


def test_fold_name_empty_falls_back_to_raw():
    assert fold_name("!!!") == "!!!"  # folds to empty -> raw lowercase


def _matrix_db(tmp_path):
    """Fixture mirroring the real names/prominence of the 22-case matrix.
    Everyone is enriched (set_popularity) so coverage >= 90% -> popularity
    is the prominence key, as post-enrichment production will be."""
    db = CollaborationDatabase(str(tmp_path / "matrix.db"))
    artists = [
        ("rihanna", "Rihanna", 5_000_000),
        ("beyonce", "Beyoncé", 6_000_000),
        ("mts", "Mariah the Scientist", 25_000),
        ("carey", "Mariah Carey", 3_430_494),
        ("adigun", "Mariah Adigun", 2),
        ("mariah", "Mariah", 1),                  # obscure exact-name collision
        ("taylor", "Taylor Swift", 8_000_000),
        ("kendrick", "Kendrick Lamar", 7_000_000),
        ("big", "Big", 10),                        # obscure exact "Big"
        ("biggie", "The Notorious B.I.G.", 2_000_000),
        ("biggiebash", "Biggie Bash", 50),
        ("tyler", "Tyler, The Creator", 4_000_000),
        ("jayz", "JAY‐Z", 5_500_000),
        ("game1", "The Game", 500_000),            # the rapper
        ("game2", "The Game", 30),
        ("game3", "The Game", 20),
        ("ye", "Ye", 4_500_000),
    ]
    for aid, name, pop in artists:
        db.add_artist(aid, name)
        db.set_popularity(aid, pop)
    db.add_artist_alias("ye", "Kanye West")
    db.add_artist_alias("biggie", "Biggie Smalls")
    return db


MATRIX = [
    # (query, expected top-1 name) — every non-gibberish case resolves (R1/R4)
    ("rihana", "Rihanna"),                       # typo, fuzzy
    ("beyonce", "Beyoncé"),                 # accent via name_norm
    ("Beyonse", "Beyoncé"),                 # phonetic typo, fuzzy
    ("Maria the scientist", "Mariah the Scientist"),
    ("Tayler Swift", "Taylor Swift"),
    ("Kendric Lamar", "Kendrick Lamar"),
    ("Mariah the", "Mariah the Scientist"),      # multiword prefix
    ("Kend", "Kendrick Lamar"),                  # prefix
    ("Notorious BIG", "The Notorious B.I.G."),   # dots deleted in fold
    ("Tyler the Creator", "Tyler, The Creator"), # comma folded
    ("JAY Z", "JAY‐Z"),                     # unicode hyphen folded
    ("Kanye West", "Ye"),                        # alias
    ("Biggie", "The Notorious B.I.G."),          # alias prefix beats junk (R5)
    ("Mariah", "Mariah Carey"),                  # exact-obscure loses (R3)
    ("The Game", "The Game"),                    # dup names, deterministic
    ("Big", "The Notorious B.I.G."),             # cross-tier override (R3)
]


@pytest.mark.parametrize("query,expected", MATRIX)
def test_resolution_matrix(tmp_path, query, expected):
    db = _matrix_db(tmp_path)
    hits = db.resolve_artist(query, limit=8)
    assert hits, f"{query!r} resolved to nothing (false dead-end, R1)"
    assert hits[0]["name"] == expected


def test_matrix_the_game_resolves_most_prominent(tmp_path):
    """3,927 duplicate-name groups: exact lookup must be deterministic and
    prominence-ordered, never arbitrary."""
    db = _matrix_db(tmp_path)
    assert db.resolve_artist("The Game")[0]["id"] == "game1"
    assert db.get_artist_by_name("The Game")["id"] == "game1"


def test_matrix_gibberish_is_honest_empty(tmp_path):
    db = _matrix_db(tmp_path)
    assert db.resolve_artist("zxqwvk") == []


def test_cross_tier_override_below_factor_exact_wins(tmp_path):
    """Below CROSS_TIER_OVERRIDE_FACTOR the tier-0 hit keeps the head —
    prominence must be DRAMATICALLY higher, not merely higher. The lower-tier
    rival here is a SUBSTRING match ("the notorious big" doesn't start with
    "big"); prefix rivals share tier 0 and follow plain popularity order
    (the settled Mariah design), which the override doesn't touch."""
    db = CollaborationDatabase(str(tmp_path / "f.db"))
    db.add_artist("exact", "Big")
    db.add_artist("near", "The Notorious B.I.G.")
    db.set_popularity("exact", 1_000)
    # 20k < 50 x 1k -> no override; exact/prefix tier keeps the head
    db.set_popularity("near", 20_000)
    hits = db.resolve_artist("Big")
    assert hits[0]["name"] == "Big"
    # ...but the prominent rival is still surfaced for the suggestions list.
    assert any(h["name"] == "The Notorious B.I.G." for h in hits)


def test_cross_tier_override_factor_pinned():
    assert CROSS_TIER_OVERRIDE_FACTOR == 50


def test_partial_enrichment_uses_degree_primary(tmp_path):
    """Mixed-coverage DB: an enriched minor artist must NOT outrank an
    unenriched superstar — degree is primary until coverage >= 90%."""
    db = CollaborationDatabase(str(tmp_path / "mix.db"))
    db.add_artist("major", "Star Major")     # unenriched: popularity 0
    db.add_artist("minor", "Star Minor")
    for i in range(5):                        # major has 5 edges
        db.add_artist(f"x{i}", f"X{i}")
        db.add_collaboration("major", f"x{i}", f"Song {i}")
    db.add_collaboration("minor", "x0", "Song m")
    db.refresh_degrees()
    db.set_popularity("minor", 25_000)        # enriched minor only
    hits = db.resolve_artist("Star")
    assert hits[0]["name"] == "Star Major"    # degree 5 beats enriched 25k pop


def test_refresh_degrees_tracks_rebuilds(tmp_path):
    """Degree is refreshable, not a one-time cache: new edges after the
    initial refresh must land on the next refresh (rebuild scenario)."""
    db = CollaborationDatabase(str(tmp_path / "deg.db"))
    for aid in ("a", "b", "c"):
        db.add_artist(aid, aid.upper())
    db.add_collaboration("a", "b", "S1")
    db.refresh_degrees()
    assert db.get_artist("a") is not None
    a_deg = db.resolve_artist("A")[0]["degree"]
    assert a_deg == 1
    db.add_collaboration("a", "c", "S2")
    db.refresh_degrees()
    assert db.resolve_artist("A")[0]["degree"] == 2


def test_legacy_db_migration_backfills_norm_and_degree(tmp_path):
    """A pre-plan DB (no norm/degree columns) opens, migrates, and matches
    accent/punctuation queries immediately (R8)."""
    import sqlite3
    p = tmp_path / "legacy.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                 "popularity INTEGER DEFAULT 0, genres TEXT DEFAULT '[]')")
    conn.execute("INSERT INTO artists VALUES ('b', 'Beyoncé', 5, '[]')")
    conn.execute("CREATE TABLE collaborations (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "artist1_id TEXT NOT NULL, artist2_id TEXT NOT NULL, "
                 "UNIQUE(artist1_id, artist2_id))")
    conn.commit()
    conn.close()
    db = CollaborationDatabase(str(p))
    hits = db.resolve_artist("beyonce")
    assert hits and hits[0]["name"] == "Beyoncé"


def test_get_artist_by_name_stays_exact_only(tmp_path):
    """verify_coverage.py depends on exact semantics: a typo returns None
    (never a fuzzy near-match), preserving the no-connection instrument."""
    db = _matrix_db(tmp_path)
    assert db.get_artist_by_name("rihana") is None
    assert db.get_artist_by_name("Rihanna")["id"] == "rihanna"


def test_disambiguate_labels_qualifier_and_tiebreak():
    cands = [
        {"id": "g1", "name": "The Game", "degree": 573},
        {"id": "g2", "name": "The Game", "degree": 3},
        {"id": "h1", "name": "HANA", "degree": 2},
        {"id": "h2", "name": "Hana", "degree": 2},   # differs only by case AND ties on count
        {"id": "u", "name": "Unique", "degree": 9},
    ]
    labels = disambiguate_labels(cands)
    assert labels[0] == "The Game · 573 collabs"
    assert labels[1] == "The Game · 3 collabs"
    assert labels[4] == "Unique"                      # no qualifier when unique
    # "HANA" vs "Hana" render identically in the uppercased buttons — they
    # must collide (qualifier) and tie-break (suffix) on the displayed form.
    assert labels[2].casefold() != labels[3].casefold()
    assert len({l.casefold() for l in labels}) == len(labels)  # visually distinct


def test_guard_search_path_uses_resolve_artist():
    """Guard (retargeted from the retired app.py test — plan 010 U6, Streamlit
    decommission): the API `/api/search` endpoint is the single resolution entry
    point for both the suggestions list and the submit button now, and it must
    resolve through `resolve_artist`. Pins against reintroducing the two-path
    split (the headline bug: suggestions via resolve_artist, submit via
    get_artist_by_name). The Next.js submit path calls this endpoint, so this is
    the modern home of the guard app.py used to carry."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / "api" / "main.py").read_text()
    # The search endpoint resolves via the single pipeline...
    assert "db.resolve_artist(" in src
    # ...and does not resolve a search query through the exact-name-only path
    # (get_artist_by_name is still used to look up Kendrick's id by name, so we
    # assert the query variable `q` is not resolved through it, not that the
    # function is absent entirely).
    assert "get_artist_by_name(q" not in src
