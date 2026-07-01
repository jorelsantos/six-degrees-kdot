---
title: "Honest not-in-network message - Plan"
date: 2026-06-30
type: feat
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
plan_depth: lightweight
---

# Honest not-in-network message - Plan

## Goal Capsule

**Objective:** Replace the app's misleading "artist not found" error with an honest message when a searched artist simply isn't in the pre-built collaboration network yet.

**Product authority:** `STRATEGY.md` (Track 1: Kendrick collaboration graph — data enrichment + public demo). This plan is scoped entirely within Track 1's public-demo-readiness work.

**Open blockers:** None.

**Product Contract preservation:** Unchanged — planning added no new product decisions beyond what the brainstorm resolved.

## Product Contract

### Summary

When a user searches for an artist not present in the pre-built collaboration network, the app currently shows `"Artist '{name}' not found."` — which reads as "this artist doesn't exist," when the artist may simply be outside the network's current reach. This plan replaces that message with an honest one that says the artist isn't in the network yet, without implying nonexistence.

### Key Decisions

- **Message-accuracy fix only, no live existence-check.** The app will not make an extra Spotify API call to distinguish "this artist doesn't exist on Spotify / was misspelled" from "this artist is real but not in the network." A single generic message covers both cases. Chosen to keep this small and shippable ahead of the ~2026-07-07 soft target, at the cost of that distinction.
- **No on-demand network expansion.** The app will not attempt to crawl an unknown artist's collaborators live when they're searched. This is a static messaging fix, not a live-lookup feature.
- **No exploration nudge in the error state.** The message states the fact and stops — no "try another artist" prompt or suggested artist. Keeps the change to messaging only.

### Requirements

- **R1.** When a searched artist is not found in the pre-built collaboration network, the app shows a message stating the artist isn't in the network yet, without implying the artist doesn't exist or was misspelled.
- **R2.** The message applies uniformly regardless of why the artist isn't found (never crawled, misspelled, or genuinely nonexistent) — no differentiated messaging by cause.
- **R3.** No new live Spotify API call is introduced by this change; the search flow's existing behavior (search only the local network) is otherwise unchanged.

### Scope Boundaries

- Live Spotify existence-check for unmatched searches — deferred, not part of this change.
- On-demand/live network expansion when an unknown artist is searched — deferred, not part of this change (this is a separate, larger idea distinct from the depth-3 rebuild already underway for Track 1).
- Any redirect/nudge behavior in the error state (e.g., suggesting another artist) — deferred, not part of this change.

### Sources / Research

- `src/database.py` (`get_artist_by_name` / `search_artists`) — confirmed search only queries the local pre-built network; no external call.
- `src/path_finder_sqlite.py` (`PathFinder.find_path`) — confirmed `find_path` returns `None` immediately if either artist isn't already in the local adjacency list; no live expansion exists anywhere in the path-finding flow.
- `app.py` (lines 439-442) — current branch: `st.error(f"Artist '{artist_name}' not found.")` plus a follow-up `st.info(...)` hint, the specific branch this plan replaces.
- Empirical verification this session: searching "Frank Sinatra" and "The Beatles" against `data/collaboration_network.db` (27,025 artists, depth-2 crawl from Kendrick) returns no match at all — both are real, well-known artists absent from the network, confirming the current message's failure mode is real and not hypothetical.
- `STRATEGY.md` — Track 1 approach ("optimize for delight, surprise, and shareability... not for being a complete or rigorously accurate database") and soft milestone (2026-07-07) directly motivated keeping this change small.

---

## Implementation Units

### U1. Replace the misleading not-found message

**Goal:** Change the search-failure message so it states the artist isn't in the network yet, without implying nonexistence or a misspelling.

**Requirements:** R1, R2, R3

**Dependencies:** None

**Files:**
- `app.py` — modify (the `st.error(...)` / `st.info(...)` pair at the artist-not-found branch, lines 439-442)

**Approach:** This is a pure string change in the existing `if not artist:` branch inside the search-handling block (`app.py`, around line 439-442). Replace the current two-line message (`"Artist '{name}' not found."` + `"Please select an artist from the suggestions above, or try a different search."`) with wording that states the artist isn't in the network yet — e.g. framing it as "not yet connected in our network" rather than "not found" — while keeping the existing suggestion-box hint intact, since that guidance is still useful and orthogonal to the wording fix. No other branch, function, or file is touched: `db.get_artist_by_name`/`search_artists` (`src/database.py`) and `PathFinder.find_path` (`src/path_finder_sqlite.py`) keep their current search-only behavior per R3 — this unit only changes what the user is told, not what the app does.

**Patterns to follow:** The existing `st.error(...)` + `st.info(...)` two-line pattern already used at this exact branch (and at `app.py:393` for the database-not-found case) — keep the same two-call shape, just change the wording.

**Test scenarios:**
- Happy path: searching an artist name that returns no match from `db.get_artist_by_name`/`search_artists` (e.g. an artist genuinely outside the network, or a misspelling) displays the new message and does not imply the artist doesn't exist.
- Edge case: searching an artist that previously triggered this exact branch (e.g. "Frank Sinatra" or "The Beatles" against the current network, confirmed absent this session) shows the updated wording, not the old "not found" phrasing.
- Test expectation: no automated test file — this repo has no existing test suite or test infrastructure (confirmed: no `tests/` directory, no test runner in `requirements.txt`), and adding one is out of scope for a single string change; verify manually by triggering the branch in the running app.

**Verification:** Running `streamlit run app.py` and searching an artist not in the network shows the new message instead of `"Artist '{name}' not found."`, and no other search behavior changes (a found artist still resolves normally).

---

## Scope Boundaries

Carried forward unchanged from the brainstorm's Scope Boundaries above — planning added no further exclusions.

---

## Verification Contract

- Searching an artist absent from the network (e.g. "Frank Sinatra") in the running app shows the new honest message, not the old "not found" phrasing.
- Searching an artist present in the network (e.g. "Drake") still resolves a connection normally — this change doesn't alter the found-artist path.
- No new network call is introduced by this change (confirm by inspecting the diff: only string literals change in the `if not artist:` branch).

## Definition of Done

- [x] Not-found message replaced with honest wording at `app.py`'s search-failure branch (U1)
- [x] Verified manually in the running app: absent artist shows new message, present artist still resolves normally
