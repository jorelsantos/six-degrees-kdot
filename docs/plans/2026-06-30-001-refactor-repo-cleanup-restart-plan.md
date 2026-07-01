---
title: "refactor: Clean up and restart Six Degrees of KDOT"
date: 2026-06-30
type: refactor
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
plan_depth: standard
---

# refactor: Clean up and restart Six Degrees of KDOT

## Summary

This project started as a SI 507 (University of Michigan) course final project — a CLI tool that finds the shortest collaboration path between any artist and Kendrick Lamar using the Spotify API, NetworkX BFS, and a hand-built pickle-based graph cache. It has since evolved, through five recent commits, into a Streamlit web app with full Spotify-brand styling (dark theme, artist profile cards, track-list-style connection view, audio preview player) backed by a SQLite collaboration-network database instead of pickle files.

The repo currently carries both eras at once: a dead pickle/CLI stack sitting alongside the live SQLite/Streamlit stack, two overlapping READMEs still framed as a course submission, a stray untracked 15MB duplicate database file at the root, and no lightweight process scaffolding (session logs, roadmap) for picking this project back up in a controlled way. This plan removes the dead code, consolidates documentation around what the app actually is today, tidies the folder structure, and adds just enough process scaffolding (a session log folder, a small scoped roadmap) to support returning to this project the way the user now works on SOS:BIO — controlled, timeline-driven, and clearly documented — without turning a cleanup pass into a rewrite.

**Product Contract preservation:** No origin document exists; this plan originates from a `ce-plan-bootstrap` session with the user (scope confirmed via `AskUserQuestion` before drafting).

---

## Problem Frame

The user is returning to `six-degrees-kdot` after a long gap and wants to reorient before building anything new. Three things are entangled and need to be pulled apart:

1. **What actually exists today** — the SQLite-backed Streamlit app is the real product; the original CLI/pickle stack is inert legacy code left over from the course project.
2. **Repo hygiene debt** — duplicate docs, a stray 15MB file, an academic PDF and README.txt sitting at the root, and a debug script mixed in with production code.
3. **Missing lightweight process** — no session log, no scoped forward roadmap, nothing that reflects the more controlled workflow habits the user has since built on SOS:BIO (small scoped feature lists, timeline thinking, safer defaults).

This is a cleanup and re-orientation pass, not new product work. No user-facing behavior of the Streamlit app changes.

---

## Requirements

- **R1.** Remove the dead pickle/CLI code path so only one system remains (SQLite + Streamlit).
- **R2.** Consolidate README.md and README.txt into a single current README that accurately describes the Streamlit app as it exists today, dropping the "SI 507 rubric compliance" academic framing.
- **R3.** Move academic/archival artifacts (FinalProject507.pdf, the retired README.txt) out of the repo root into a clearly-labeled archive location, preserved rather than deleted.
- **R4.** Relocate the standalone debug utility (debug_albums.py) out of the repo root into a dedicated scripts/ location.
- **R5.** Delete the stray untracked duplicate database file at the repo root.
- **R6.** Add a lightweight `sessions/` folder so the user's `/session-wrap` habit (carried over from SOS:BIO) has a home in this repo.
- **R7.** Add a small, explicitly scoped (5-6 item) forward roadmap document reflecting the user's "stay controlled" preference, not an open-ended backlog.
- **R8.** Keep `data/collaboration_network.db` tracked in git as-is (explicit user decision — the tracked DB is not touched by this plan).

---

## Key Technical Decisions

**KTD1 — Delete the legacy CLI stack rather than archive it.**
`main.py`, `src/network_builder.py`, and `src/path_finder.py` (pickle-based) are fully superseded by `app.py` + `src/build_network_sqlite.py` + `src/database.py` + `src/path_finder_sqlite.py`. A repo-wide reference scan found no code path importing the legacy modules from the live app — only the legacy files reference each other, and only the old README.md/README.txt mention `main.py`. Git history preserves the code if it's ever needed again, so archiving in-tree adds clutter without adding safety. *(User-confirmed via AskUserQuestion.)*

**KTD2 — Keep `src/data_fetcher.py` as shared infrastructure.**
It is the Spotify API client used by both the legacy stack (being deleted) and the live stack (`app.py`, `src/build_network_sqlite.py`, `scripts/debug_albums.py`). No changes needed to this file beyond confirming it has no legacy-only code paths.

**KTD3 — Archive, don't delete, academic artifacts.**
FinalProject507.pdf and the retired README.txt have provenance value (this was a real course project) but don't belong at the repo root of an active side project. `docs/archive/` keeps them discoverable without them being the first thing a visitor or the user sees.

**KTD4 — Keep `data/collaboration_network.db` tracked in git.**
The user explicitly chose to keep the ~15MB SQLite DB committed rather than switch to a gitignored + regenerate-on-clone model, prioritizing "clone and run" simplicity over repo-size hygiene for now. This plan does not touch `.gitignore` rules for `data/collaboration_network.db` or the `data/*` JSON cache ignore rule (already correct). Revisiting this is explicitly out of scope (see Scope Boundaries).

**KTD5 — New docs live under `docs/`, not scattered at root.**
`docs/archive/` for retired artifacts, `docs/ROADMAP.md` for the scoped forward plan. This keeps the root directory limited to the files a new visitor actually needs (README, app entrypoint, requirements, config), matching the "build things out more clearly" lesson from SOS:BIO.

---

## Output Structure

```text
six-degrees-kdot/
├── README.md                  # rewritten, single source of truth
├── app.py                     # unchanged — Streamlit entrypoint
├── requirements.txt           # modified — networkx removed (U1)
├── .env.example                # unchanged
├── .streamlit/config.toml     # unchanged
├── data/
│   ├── .gitkeep
│   └── collaboration_network.db   # unchanged, stays tracked
├── src/
│   ├── __init__.py
│   ├── data_fetcher.py
│   ├── database.py
│   ├── build_network_sqlite.py
│   └── path_finder_sqlite.py
│   # (network_builder.py, path_finder.py removed)
├── scripts/
│   └── debug_albums.py        # moved from repo root
├── sessions/
│   └── .gitkeep                # new — home for /session-wrap logs
├── docs/
│   ├── ROADMAP.md              # new — 5-6 scoped next features
│   ├── archive/
│   │   ├── FinalProject507.pdf     # moved from repo root
│   │   └── README-si507.txt        # renamed from README.txt, moved
│   └── plans/
│       └── 2026-06-30-001-refactor-repo-cleanup-restart-plan.md
# (main.py removed)
# (debug_albums.py removed from root, see scripts/)
# ("collaboration_network.db copy" deleted, was untracked)
```

---

## Implementation Units

### U1. Remove the legacy pickle/CLI stack

**Goal:** Delete the superseded CLI application and its pickle-based graph modules so only the SQLite/Streamlit system remains.

**Requirements:** R1

**Dependencies:** None

**Files:**
- `main.py` — delete
- `src/network_builder.py` — delete
- `src/path_finder.py` — delete
- `requirements.txt` — modify (remove `networkx`, used only by the deleted legacy stack)

**Approach:** Straight deletion. Before deleting, re-confirm no other tracked file imports these three modules (the repo scan in KTD1 already found none outside themselves and the old README). `src/__pycache__/` entries for these modules are build artifacts and already gitignored — no action needed there beyond normal `__pycache__` regeneration. `networkx` is only imported by the legacy modules being deleted — confirm no other tracked file imports it, then remove it from `requirements.txt` so a fresh clone doesn't install an unused dependency.

**Patterns to follow:** N/A (deletion-only unit).

**Test scenarios:**
- Test expectation: none -- pure deletion of unreferenced code; no behavior change to verify beyond the app still running (covered by U6 verification).

**Verification:** `git grep` for `network_builder` and `path_finder\b` (excluding `path_finder_sqlite`) returns no hits outside git history/this plan file. `streamlit run app.py` still starts and a path lookup still works (shared verification with U6).

---

### U2. Relocate the debug utility into scripts/

**Goal:** Move `debug_albums.py` out of the repo root into a dedicated `scripts/` folder so root-level files are limited to entrypoints and config.

**Requirements:** R4

**Dependencies:** None

**Files:**
- `scripts/debug_albums.py` — new (moved from `debug_albums.py`)
- `debug_albums.py` — delete (post-move)

**Approach:** `git mv debug_albums.py scripts/debug_albums.py`. The script does `sys.path.insert(0, 'src')`, which is a relative path assuming the script is invoked from the repo root — update it to resolve relative to the repo root explicitly (e.g., via `Path(__file__).parent.parent / "src"`) so it still works when run from `scripts/` or anywhere else, matching the pattern already used in `app.py`.

**Patterns to follow:** `app.py`'s `sys.path.insert(0, str(Path(__file__).parent / "src"))` pattern — adapt for the one-level-deeper `scripts/` location.

**Test scenarios:**
- Happy path: running `python3 scripts/debug_albums.py` from the repo root still successfully imports `data_fetcher` and prints album data for Kendrick Lamar, same as before the move.

**Verification:** Script runs without `ModuleNotFoundError` when invoked from the repo root.

---

### U3. Delete the stray untracked duplicate database file

**Goal:** Remove `collaboration_network.db copy` from the repo root.

**Requirements:** R5

**Dependencies:** None

**Files:**
- `collaboration_network.db copy` — delete

**Approach:** The file is untracked (confirmed via `git status`) and not referenced by any code (only `data/collaboration_network.db` is used by `app.py`). Direct filesystem deletion; no git operation needed since it was never committed.

**Patterns to follow:** N/A.

**Test scenarios:**
- Test expectation: none -- deleting an unreferenced, untracked file with no code path pointing to it.

**Verification:** `ls` at repo root no longer shows the file; `git status` shows no change (it was never tracked).

---

### U4. Archive academic artifacts

**Goal:** Move the course-submission artifacts out of the repo root into `docs/archive/`, preserved but no longer front-and-center.

**Requirements:** R3

**Dependencies:** None (this unit only moves FinalProject507.pdf and README.txt — it does not touch README.md, so it has no ordering dependency on U5)

**Files:**
- `docs/archive/FinalProject507.pdf` — new (moved from `FinalProject507.pdf`)
- `docs/archive/README-si507.txt` — new (moved from `README.txt`, renamed for clarity since it will sit next to the new README)
- `FinalProject507.pdf` — delete (post-move)
- `README.txt` — delete (post-move)

**Approach:** `git mv FinalProject507.pdf docs/archive/FinalProject507.pdf` and `git mv README.txt docs/archive/README-si507.txt`. No content changes to either file — this is a pure relocation preserving the original academic writeup as historical record.

**Patterns to follow:** N/A.

**Test scenarios:**
- Test expectation: none -- file relocation with no content change.

**Verification:** Both files present at their new paths; repo root no longer contains `FinalProject507.pdf` or `README.txt`.

---

### U5. Rewrite README.md as the single current source of truth

**Goal:** Replace the academic-framed README.md with one that accurately describes the Streamlit app as it exists today — what it does, how to run it, and its current architecture — dropping "SI 507 rubric compliance" language entirely.

**Requirements:** R2

**Dependencies:** U1 (so setup instructions don't reference the deleted `main.py`/`src/network_builder.py` CLI flow)

**Files:**
- `README.md` — rewrite

**Approach:** Keep the useful bones (project pitch, quick start, Spotify API credential setup, features list) but:
- Remove all references to `main.py`, `python3 src/network_builder.py`, and the CLI flow — replace with `streamlit run app.py` as the only run path, and `python3 src/build_network_sqlite.py` (or whatever the current SQLite build entrypoint is) as the network-build step if one is still required before first run.
- Remove "SI 507," "rubric," "course," and similar academic-submission language. A single line noting the project's origin ("originally built as a University of Michigan SI 507 course project, since rebuilt as a Streamlit app") is fine context but should not frame the whole document.
- Update the architecture section to describe the SQLite-backed graph (`src/database.py`, `src/path_finder_sqlite.py`) instead of the pickle-based one.
- Add a short "Project history" or "Status" note pointing to `docs/archive/` for the original course writeup, and to `docs/ROADMAP.md` for what's planned next.
- Verify the Quick Start steps actually match the current `app.py` + SQLite flow by cross-checking against `src/build_network_sqlite.py` and `app.py`'s `load_database()`/`load_path_finder()` functions for the real setup sequence (DB path, env vars needed).

**Patterns to follow:** Existing README.md's Quick Start / Getting Started structure is reasonable and can be kept — only the CLI-specific and academic content needs to change.

**Test scenarios:**
- Test expectation: none -- documentation content change; validated qualitatively via U6's fresh-read walkthrough.

**Verification:** A person unfamiliar with the project can read README.md top to bottom and arrive at a correct `streamlit run app.py` setup with no mention of the deleted CLI files or course rubric language.

---

### U6. Add sessions/ scaffolding

**Goal:** Give the `/session-wrap` workflow a home in this repo, matching how it's used in SOS:BIO.

**Requirements:** R6

**Dependencies:** None

**Files:**
- `sessions/.gitkeep` — new

**Approach:** Create the empty `sessions/` directory (git needs a placeholder file to track an empty dir) so the next `/session-wrap` run has somewhere to write its dated log without first creating the folder by hand. No README or template file inside it is needed — `/session-wrap` generates its own log format.

**Patterns to follow:** N/A — this mirrors the `data/.gitkeep` pattern already used in this repo for tracking an otherwise-empty, mostly-gitignored directory.

**Test scenarios:**
- Test expectation: none -- scaffolding only.

**Verification:** `sessions/` directory exists and is tracked in git via `.gitkeep`.

---

### U7. Write a scoped 5-6 item roadmap

**Goal:** Produce `docs/ROADMAP.md` — a short, explicitly bounded list of the next features/fixes for the Streamlit app, reflecting the user's "stay controlled, don't sprawl" preference from SOS:BIO.

**Requirements:** R7

**Dependencies:** U5 (so the roadmap can be linked from the new README)

**Files:**
- `docs/ROADMAP.md` — new

**Approach:** Structure as a simple dated list, not a kanban board or exhaustive backlog:
- A one-line "current state" summary (Streamlit app, SQLite-backed, Spotify-styled, working).
- Exactly 5-6 candidate next items, each one line: what + why it matters. Draw candidates from what's naturally next for this app given its current shape (e.g., broadening the pre-built network beyond depth-2/3 from Kendrick, surfacing degrees-of-separation for artists not yet in the network without a slow live rebuild, mobile-responsive layout check, a lightweight test for `path_finder_sqlite`'s BFS correctness, deploying the Streamlit app somewhere public, trimming/rotating the local JSON API-response cache in `data/`). These are illustrative candidates for the document — the user should adjust/reorder them to their actual priorities when they next open this file; the roadmap's job is to exist and be short, not to lock in a specific feature order.
- No fixed timeline/dates baked in (the user said they want "a timeline of products and features" as a practice, but assigning real dates to a side project roadmap during a cleanup pass would be inventing scope) — instead leave a "target" column/field per item that's empty or marked TBD, for the user to fill in themselves once they've decided what's actually next.

**Patterns to follow:** N/A — new document, no existing roadmap format in this repo to mirror.

**Test scenarios:**
- Test expectation: none -- planning document, not executable code.

**Verification:** `docs/ROADMAP.md` exists, contains exactly 5-6 items, and is linked from README.md.

---

### U8. Final repo-wide reference sweep

**Goal:** Catch any remaining stale references to deleted/moved files across the whole repo before calling the cleanup done.

**Requirements:** R1, R2, R3, R4

**Dependencies:** U1, U2, U3, U4, U5

**Files:** None created. Verification-only unit; may produce follow-up edits to `README.md` or `.streamlit/config.toml` if a stray reference is found during the sweep.

**Approach:** Run `git grep` (or equivalent) across all tracked files for: `main.py`, `network_builder`, `debug_albums.py` (root path form), `FinalProject507.pdf`, `README.txt`, `collaboration_network.db copy`, and `networkx`. Confirm every remaining hit is either (a) inside `docs/plans/` (this plan, which legitimately documents the change) or (b) inside `docs/archive/` (the archived files' own content, which is expected to still say what it always said). Any hit outside those two locations is a stale reference to fix.

**Patterns to follow:** N/A.

**Test scenarios:**
- Test expectation: none -- verification sweep, not new behavior.

**Verification:** `streamlit run app.py` starts cleanly, loads `data/collaboration_network.db`, and a sample search (e.g., "Drake") returns a path to Kendrick Lamar — confirming the cleanup didn't break the live app. `git status` shows the expected set of deletions/moves/additions and nothing unintended.

---

## Scope Boundaries

**In scope:** Removing dead code, consolidating docs, relocating archival/debug files, adding `sessions/` and `docs/ROADMAP.md` scaffolding, verifying the app still runs after cleanup.

**Out of scope (non-goals for this plan):**
- Any new user-facing feature in the Streamlit app itself.
- Changing how `data/collaboration_network.db` is tracked in git (explicit user decision to keep it as-is).
- Adding a test suite or CI — no test infrastructure exists today; introducing one is a separate, larger decision.
- Rotating, pruning, or restructuring the 38,000+ gitignored JSON cache files in `data/` — they're already correctly ignored and out of git's concern.

### Deferred to Follow-Up Work
- Automated tests for `src/path_finder_sqlite.py`'s BFS logic (flagged as a roadmap candidate in U7, not built here).
- CI/CD setup.
- A CHANGELOG.md — the user's ask was specifically for a repo cleanup + scoped roadmap, not full process tooling; revisit if `/session-wrap` logs make a changelog feel warranted later.
- Revisiting whether `data/collaboration_network.db` should move out of git entirely (KTD4) — explicitly deferred by the user's own choice, not by planning oversight.

---

## Verification Contract

- After all units land, `streamlit run app.py` starts without import errors.
- A live search in the running app (e.g., searching "Drake") returns a valid connection path to Kendrick Lamar, confirming `data/collaboration_network.db` and `src/path_finder_sqlite.py` still work post-cleanup.
- `git grep` sweep (U8) shows no stale references to deleted/moved files outside `docs/plans/` and `docs/archive/`.
- Repo root contains only: `README.md`, `app.py`, `requirements.txt`, `.env.example`, `.gitignore`, `.streamlit/`, `data/`, `src/`, `scripts/`, `sessions/`, `docs/` (plus standard dotfiles).

## Definition of Done

- [ ] Legacy CLI stack deleted (U1)
- [ ] Debug script relocated to `scripts/` (U2)
- [ ] Stray duplicate DB file deleted (U3)
- [ ] Academic artifacts archived under `docs/archive/` (U4)
- [ ] README.md rewritten as single current source of truth (U5)
- [ ] `sessions/` scaffolded (U6)
- [ ] `docs/ROADMAP.md` written with 5-6 scoped items (U7)
- [ ] Repo-wide reference sweep clean and app verified working (U8)
