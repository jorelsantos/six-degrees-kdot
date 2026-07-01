---
name: Rabbit Hole
last_updated: 2026-06-30
---

# Rabbit Hole Strategy

## Target problem

Music fans want to know how their favorite artists connect to reference points (regional heroes, favorite artists) through real collaborations, and to stumble onto connections they didn't expect — but tracing that web across scattered discographies, credits, and liner notes takes more digging than any curious fan will actually do.

## Our approach

We win by optimizing for delight, surprise, and shareability in every search — not for being a complete or rigorously accurate music-collaboration database. The pre-built network only needs to be deep enough to reliably produce a "no way, really?" moment, not exhaustive.

## Who it's for

**Primary:** Curious fans exploring solo — they're hiring Rabbit Hole to surface a surprising artist connection, which sends them straight to Spotify/YouTube to verify it and learn more about the artists and the wider web of music they love.

## Key metrics

- **No-connection-found rate** - % of searched artists that fail to resolve a path; tracked via a counter in the demo app.
- **Repeat-search rate per session** - how often someone searches a 2nd/3rd artist in one visit ("one more" behavior); same lightweight session logging.
- **Shares/link-outs** - clicks on a share action (or informal signal — screenshots/DMs people send you) tracking virality/delight.

## Tracks

### Track 1: Kendrick collaboration graph

Data enrichment (deeper/richer collaboration network) plus a public, shareable demo. This is the current codebase and the immediate focus.

_Why it serves the approach:_ Directly tests whether the pre-built network is rich enough to produce delight at real scale, with real strangers.

### Track 2: Rabbit Hole UI/UX platform

Move off Streamlit; build a custom, Spotify-inspired design system with real UI/UX craft.

_Why it serves the approach:_ Delight and shareability depend on how it feels, not just what it finds — a generic Streamlit UI caps how surprising/fun this can feel.

### Track 3: Open-source template

Generalize beyond Kendrick so anyone can plug in their own Spotify developer key and their own favorite artist as the graph's center.

_Why it serves the approach:_ Extends the same delight loop to any fan's own favorite artist, not just Kendrick fans.

### Track 4: Thematic/listening-pattern analysis

The original "Rabbit Hole" idea: take a user's top 20-25 songs and surface themes/samples/lineages they didn't consciously notice.

_Why it serves the approach:_ Same discovery/delight loop, one level deeper — subconscious patterns instead of collaboration paths.

## Milestones

- **2026-07-07** (soft target, ~1 week out) - Track 1 demo live and shareable.

## Marketing

**One-liner:** If you want to learn something new about music, just type in random artists and you'll have a lot of fun.
