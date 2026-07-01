---
title: "Fix rebuild-stall bugs, verify with small sample, run full depth-3 rebuild - Plan"
date: 2026-07-01
type: fix
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
plan_depth: lightweight
---

# Fix rebuild-stall bugs, verify with small sample, run full depth-3 rebuild - Plan

## Summary

The depth-3 rebuild (docs/plans/2026-06-30-004-feat-depth3-rebuild-public-demo-plan.md, U3) stalled twice: once from a missing request timeout, once from a threading limitation that a request-level timeout alone can't fix. Both are now fixed in `src/data_fetcher.py` and `src/build_network_sqlite.py`. This plan verifies the fix against a small live sample before committing to the full ~5-7 hour run, then executes and monitors that run to completion.

## Problem Frame

Two incidents, same symptom (zero progress, zero CPU activity, process still "alive"):
1. **Incident 1** (PID 30726, this session's sandbox): `requests.post`/`requests.get` had no `timeout=`, so a stalled connection during a session disruption blocked a worker thread forever. Fixed by adding `timeout=30` to both calls.
2. **Incident 2** (PID 39512, user's own terminal, post-fix): stalled again within minutes despite the timeout fix. Live inspection (`lsof -p 39512`) showed exactly 5 ESTABLISHED TCP connections (matching `max_workers=5`) with zero CPU activity for 9+ minutes — consistent with a socket-level block that a `timeout=` parameter alone doesn't reliably interrupt in all cases, combined with the fact that Python threads cannot be force-killed and `ThreadPoolExecutor`'s `with`-block shutdown waits for every submitted task regardless. Fixed by rewriting `build_network()`'s batch-collection loop to poll with `concurrent.futures.wait(..., timeout=90, return_when=FIRST_COMPLETED)` and give up on remaining pending futures after 3 consecutive stalled polls (~4.5 min), then `executor.shutdown(wait=False, cancel_futures=True)` so the level (and the process) never blocks on a wedged thread again. Abandoned artists simply stay uncrawled and get picked up on the next `--resume`.

Both fixes are already implemented and committed to `src/data_fetcher.py` / `src/build_network_sqlite.py` on branch `feat/depth3-rebuild-and-deploy`. What's not yet done: verifying the second fix actually works against live traffic (it was only verified with a simulated stuck-thread test, not real Spotify calls) before committing another 5-7 hours to the full run.

## Requirements

- **R1.** Kill the currently-stalled process (PID 39512) before starting anything new, so it doesn't leave a zombie/orphaned crawl fighting the new run for rate-limit budget.
- **R2.** Verify the fixed code against a small, live sample (a handful of real artists, real Spotify API calls) before launching the full depth-3 rebuild — specifically confirming the bounded-wait logic lets the process continue making progress even if one call is slow, and that it doesn't regress normal-case behavior.
- **R3.** Only after R2 passes, launch the full depth-3 `--resume` rebuild (keeping the 846 already-crawled artists) as a properly monitored background process.
- **R4.** Monitor to actual completion (or a genuine, reported failure) — not silently walk away.

## Key Technical Decisions

**KTD1 — Verify with a small depth, not a dry run of the full crawl.** The fastest, most direct way to confirm the fix works against real traffic is to run `build_network()` at a tiny scope (e.g., a small subset of artists, not the full depth-3 fan-out) and confirm it completes and produces sane output, rather than trying to simulate the exact stall condition (which was likely environment/network-specific and may not reproduce on demand).

**KTD2 — Reuse the existing `--resume` flow for the real run.** No need for a third flag or mode; the small-sample verification is a separate, throwaway invocation against a temporary/small scope, and the real run is the same `--resume --depth 3` command already established.

## Implementation Units

### U1. Kill the stalled process and confirm clean state

**Goal:** Ensure no competing/zombie crawl process is running before starting the verification or the real run.

**Requirements:** R1

**Dependencies:** None

**Files:** None (operational step).

**Approach:** Confirm PID 39512 (or any other `build_network_sqlite.py` process) is not running; if it is, terminate it. Confirm the database's `crawled` count still reflects the last known-good state (846 or higher, never lower) before proceeding.

**Test scenarios:**
- Test expectation: none — operational verification step.

**Verification:** `ps aux | grep build_network_sqlite` shows no matching process; `SELECT COUNT(*) FROM artists WHERE crawled=1` is consistent with the last known state.

---

### U2. Small live-sample verification run

**Goal:** Confirm the fixed code (timeout + bounded-wait) works correctly against real Spotify traffic before committing to the full run.

**Requirements:** R2

**Dependencies:** U1

**Files:** None (verification uses existing code as-is; no new test file, since this repo has no test infrastructure and the fix was already unit-verified with a simulated stuck thread — this step is about real-network confidence, not code correctness).

**Approach:** Run a small, bounded live crawl — e.g., invoke `build_network()` directly (not via `main()`) with a tiny `starting_artist_id` set and low `depth`/artist count, so it touches real Spotify endpoints but completes in well under a minute if healthy. Confirm: (a) it completes without hanging, (b) artists get correctly marked `crawled`, (c) if any single call is naturally slow, the process still makes overall progress rather than freezing. This is a smoke test of the exact fix, not a full behavioral test suite — proportionate to a hobby project with no existing test infrastructure.

**Test scenarios:**
- Happy path: a small live crawl (e.g., 3-5 artists) completes within a short, bounded time and all touched artists are marked `crawled=1`.
- Resilience check: if feasible to observe within this small run, confirm the bounded-wait path doesn't fire spuriously under normal healthy conditions (i.e., it only kicks in when something is actually stuck, not on ordinary slow-but-working requests).

**Verification:** The small sample run completes cleanly, with clear pass/fail evidence (not just "looked fine") before proceeding to U3.

---

### U3. Launch the full depth-3 rebuild (monitored)

**Goal:** Run the real, full rebuild with confidence, and know definitively when it finishes or fails.

**Requirements:** R3, R4

**Dependencies:** U2 (must pass first)

**Files:** None.

**Approach:** Launch `python3 src/build_network_sqlite.py --resume --depth 3` as a properly backgrounded, disowned process (in the user's own terminal, consistent with this session's earlier decision to decouple long-running work from any AI session's fate). Set up a monitor that tracks real progress (not just process-alive status) and distinguishes "still working" from "stalled" from "done," and reports the actual outcome rather than requiring manual polling.

**Test scenarios:**
- Test expectation: none — this is the real operational run, not new code; its own success/failure IS the verification.

**Verification:** The rebuild either completes (reflected in a materially larger `crawled` count and a sane BFS degree distribution) or fails with a clear, understood reason — never silently stalls unnoticed again.

## Scope Boundaries

**In scope:** Fixing and verifying the two stall bugs, then completing the rebuild that was already planned in docs/plans/2026-06-30-004-feat-depth3-rebuild-public-demo-plan.md's U3.

**Out of scope:** Everything else in that original plan (U4 verification of network coverage, U5 ROADMAP reconciliation, U6/U7 deployment) — those resume once this rebuild actually finishes, per the original plan, not re-litigated here.

## Verification Contract

- No stalled/zombie crawl process running before the real run starts.
- Small live-sample run completes and demonstrates the fix works against real traffic.
- Full rebuild either completes with a materially improved network, or fails with a clearly reported, understood cause — not another silent multi-hour stall.

## Definition of Done

- [ ] Stalled process killed, clean state confirmed (U1)
- [ ] Small live-sample verification passed (U2)
- [ ] Full rebuild launched, monitored, and resolved to completion or a clear failure (U3)
