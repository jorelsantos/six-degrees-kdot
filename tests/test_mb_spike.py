"""
Offline unit tests for the U8 spike's edge-derivation and dedup logic.

No live calls: everything runs against captured/synthetic MusicBrainz-shaped
credit JSON, exercising the non-negotiable rules (co-credit-only edges,
MBID-keyed nodes with name collapse, version dedup to a canonical song).
"""

import mb_spike as mb


# --- captured-shape sample credit JSON (mirrors the real API) ---------------

def _credit(mbid, canonical_name, credited_as=None, join=""):
    return {
        "artist": {"id": mbid, "name": canonical_name},
        "name": credited_as or canonical_name,
        "joinphrase": join,
    }


def _rec(title, credits):
    return {"title": title, "artist-credit": credits}


KDOT = "381086ea-f511-4aba-bdf9-71c753dc5077"
KANYE = "164f0d73-1234-4e2c-8743-d77bf2191051"
SZA = "sza-mbid"
DRE = "dre-mbid"


# --- parse_credits ----------------------------------------------------------

def test_parse_credits_extracts_mbid_and_canonical_name():
    rec = _rec("HUMBLE.", [_credit(KDOT, "Kendrick Lamar")])
    assert mb.parse_credits(rec) == [(KDOT, "Kendrick Lamar")]


def test_ye_and_kanye_collapse_to_one_mbid_node():
    # Same MBID credited under two different display names must collapse (KTD7).
    rec = _rec("No More Parties in LA", [
        _credit(KANYE, "Kanye West", credited_as="Ye", join=" feat. "),
        _credit(KDOT, "Kendrick Lamar"),
    ])
    credits = mb.parse_credits(rec)
    kanye_entries = [c for c in credits if c[0] == KANYE]
    assert len(kanye_entries) == 1
    # Canonical artist name is used as the display name, not the credited alias.
    assert kanye_entries[0][1] == "Kanye West"


def test_parse_credits_dedups_repeated_artist_within_recording():
    rec = _rec("X", [_credit(KDOT, "Kendrick Lamar"), _credit(KDOT, "Kendrick Lamar")])
    assert mb.parse_credits(rec) == [(KDOT, "Kendrick Lamar")]


def test_parse_credits_skips_entries_missing_id_or_name():
    rec = _rec("X", [{"artist": {"name": "No ID"}}, _credit(KDOT, "Kendrick Lamar")])
    assert mb.parse_credits(rec) == [(KDOT, "Kendrick Lamar")]


# --- derive_edges: the co-credit-only rule ----------------------------------

def test_solo_recording_yields_no_edge():
    recs = [_rec("u", [_credit(KDOT, "Kendrick Lamar")])]
    acc = mb.derive_edges(recs)
    assert list(acc.edges()) == []


def test_three_artists_yield_all_pairs():
    recs = [_rec("Song X", [
        _credit("A", "A"), _credit("B", "B"), _credit("C", "C"),
    ])]
    acc = mb.derive_edges(recs)
    assert set(acc.edges()) == {("A", "B"), ("A", "C"), ("B", "C")}
    for a, b in acc.edges():
        assert acc.representative_songs(a, b) == ["Song X"]


def test_join_phrase_is_not_required_for_edge():
    # "A feat. B" still produces the A-B edge; the join phrase is informational.
    recs = [_rec("Collab", [
        _credit("A", "A", join=" feat. "), _credit("B", "B"),
    ])]
    acc = mb.derive_edges(recs)
    assert set(acc.edges()) == {("A", "B")}


def test_missing_artist_id_does_not_abort_run():
    recs = [
        _rec("Bad", [{"artist": {}}, _credit("A", "A")]),  # one broken credit
        _rec("Good", [_credit("A", "A"), _credit("B", "B")]),
    ]
    acc = mb.derive_edges(recs)
    assert ("A", "B") in set(acc.edges())


# --- dedup / canonical song selection (KTD8) --------------------------------

def test_base_title_normalizes_variants():
    assert mb.base_title("All Day") == "all day"
    assert mb.base_title("All Day (Remix)") == "all day"
    assert mb.base_title("All Day - Radio Edit") == "all day"
    assert mb.base_title("All Day (feat. Paul McCartney)") == "all day"


def test_is_variant_title():
    assert mb.is_variant_title("All Day (Remix)")
    assert mb.is_variant_title("HUMBLE. - Live")
    assert not mb.is_variant_title("All Day")
    assert not mb.is_variant_title("HUMBLE.")


def test_version_sprawl_dedups_to_one_canonical_song():
    # "All Day" plus two remixes must collapse to a single clean canonical title.
    recs = [
        _rec("All Day", [_credit(KANYE, "Kanye West"), _credit("PM", "Paul McCartney")]),
        _rec("All Day (Remix)", [_credit(KANYE, "Kanye West"), _credit("PM", "Paul McCartney")]),
        _rec("All Day - Radio Edit", [_credit(KANYE, "Kanye West"), _credit("PM", "Paul McCartney")]),
    ]
    acc = mb.derive_edges(recs)
    songs = acc.representative_songs(KANYE, "PM")
    assert songs == ["All Day"]


def test_repeated_collab_across_distinct_songs_keeps_both():
    recs = [
        _rec("A1 Everything", [_credit("X", "X"), _credit("Y", "Y")]),
        _rec("Alright", [_credit("X", "X"), _credit("Y", "Y")]),
    ]
    acc = mb.derive_edges(recs)
    songs = set(acc.representative_songs("X", "Y"))
    assert songs == {"A1 Everything", "Alright"}


def test_representative_songs_respects_cap():
    recs = [_rec(f"Song {i}", [_credit("X", "X"), _credit("Y", "Y")]) for i in range(10)]
    acc = mb.derive_edges(recs)
    assert len(acc.representative_songs("X", "Y", cap=3)) == 3


# --- accumulator neighbor lookups (drive the BFS) ---------------------------

def test_neighbors_are_undirected():
    recs = [_rec("S", [_credit("A", "A"), _credit("B", "B")])]
    acc = mb.derive_edges(recs)
    assert acc.neighbors("A") == ["B"]
    assert acc.neighbors("B") == ["A"]
