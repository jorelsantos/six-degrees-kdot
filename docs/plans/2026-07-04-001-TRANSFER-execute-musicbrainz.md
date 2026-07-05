# Transfer / Execution Handoff — MusicBrainz graph migration

**How to use:** paste the block below into a fresh Claude Code session opened in the
`six-degrees-kdot` repo. It is self-contained. The new session executes; it should not re-plan.

---

I'm starting a fresh session to **execute** an implementation-ready plan for Rabbit Hole
(the `six-degrees-kdot` Kendrick Lamar collaboration-network project). Everything is already
decided — your job is to build it, not re-plan it. Work through the plan's Implementation
Units and stop at genuine blockers.

## Read first (source of truth)
- **The plan:** `docs/plans/2026-07-04-001-feat-musicbrainz-graph-migration-plan.md` — read it
  fully. It has the Requirements, Key Technical Decisions (KTD1–KTD9), Implementation Units
  (U8 first, then U1–U7), Verification Contract, and Definition of Done.
- Prior context lives in `sessions/` (latest session log) and `STRATEGY.md`.

## What we're doing (one paragraph)
We abandoned the Spotify bulk crawl — it kept hitting escalating multi-hour rate-limit
penalties (9.8h then 21.7h) even at conservative settings, and only got ~12% done. We're
rebuilding the collaboration graph from a **MusicBrainz dump** (CC0, downloadable, no rate
limit) and moving previews to **iTunes Search API + Deezer** (Spotify deprecated `preview_url`
for dev-mode apps). First iteration is **depth 2 only** — build small, learn the data, expand
later.

## Non-negotiable rules (do NOT violate)
1. **Connection = shared recording only.** An edge exists ONLY when 2+ artists are co-credited
   on the same recording, and that recording IS the connecting song. No membership/relationship
   edges. A band and its members are **distinct nodes** — never substitute one for the other
   (validated: The Beatles have ~0 co-credits → "no connection", and are NOT reachable via
   Paul McCartney, who resolves at degree-1 via Kanye's "All Day"). Every edge must carry a
   playable song.
2. **Key nodes on MBID, not display name** ("Ye" and "Kanye West" are one artist).
3. **Do NOT discard the Spotify data or crawler.** Build MusicBrainz into a SEPARATE database
   `data/collaboration_network_mb.db`; the existing `data/collaboration_network.db` and the
   Spotify crawler stay as a retained fallback. App cutover is a reversible config switch.
4. **Depth 2 only** this iteration. Do not go deeper without a new decision.
5. **Do NOT deploy.** Public deployment is explicitly deferred to a later plan.

## Execution order
1. **U8 — Validation spike FIRST (it gates everything).** Build a tiny depth-2 graph from
   Kendrick via the live MusicBrainz API (1 req/sec, descriptive `User-Agent`), load it into
   the real app, and confirm the acceptance checks: McCartney resolves; The Beatles returns no
   connection; "Ye"/"Kanye West" collapse to one MBID node; recording versions dedup to one
   canonical song; every path hop carries a song; an iTunes/Deezer preview plays. **Only proceed
   to the full build if these pass.**
2. **U1 → U2 → U3** — download/stage the MusicBrainz core dump subset (4 tables: `artist`,
   `artist_credit`, `artist_credit_name`, `recording`); derive co-credit edges with connecting
   songs; depth-2 BFS build into the new DB.
3. **U4** — iTunes(primary)+Deezer(fallback) preview swap (can run in parallel with U1–U3).
4. **U5** — reversible app cutover to the new DB. **U6** — verify coverage (McCartney found,
   Beatles correctly isolated, degree distribution vs. the retained Spotify baseline). **U7** —
   reconcile docs + MusicBrainz/Apple attribution.

## Operational notes
- Run any long local job (the dump ingest) in the **user's own terminal** (`nohup … & disown`),
  NOT the AI session's sandbox — a profile switch has killed a run before. (The MusicBrainz
  build has no rate limits, so this is lower-stakes than the old Spotify crawl, but keep the
  habit.)
- Be a good MusicBrainz citizen: descriptive `User-Agent`, respect 1 req/sec on the live API.
  Bulk work uses the downloaded dump (no rate limit).
- Repo builds/scripts should be run so the user can see them; confirm before anything
  hard-to-reverse.

## Do NOT build now (pinned for later)
- Depth expansion beyond 2.
- A separate **producer/credits graph** (producers, writers, engineers — Metro Boomin, Pharrell,
  etc.); it's a future work tree needing its own product framing.
- Public deployment (Streamlit) — resumes from
  `docs/plans/2026-06-30-004-feat-depth3-rebuild-public-demo-plan.md` after this graph is built
  and verified.

Follow the plan's Verification Contract and Definition of Done. Surface genuine blockers
(anything that changes scope or contradicts the plan) instead of guessing.
