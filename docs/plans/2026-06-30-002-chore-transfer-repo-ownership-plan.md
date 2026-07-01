---
title: "chore: Transfer six-degrees-kdot from school to personal GitHub account"
date: 2026-06-30
type: chore
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
plan_depth: standard
---

# chore: Transfer six-degrees-kdot from school to personal GitHub account

## Summary

`six-degrees-kdot` currently lives at `github.com/jorelsantos-um` — a University of Michigan school-affiliated GitHub account. Now that the user is actively reviving this as a personal side project, they want it owned by their personal account, `github.com/jorelsantos`, going forward.

Research confirms this is a straightforward, low-risk transfer: `jorelsantos-um` owns the repo as a personal **User** account (not as `umsi-class` or `casmlab`, the orgs it happens to belong to), so no org-transfer-approval policy applies. The repo has zero webhooks, no GitHub Pages, no Actions secrets or workflows, no branch protection, and only one collaborator (the owner) — there is very little to break. GitHub's native "Transfer ownership" feature carries over issues, pull requests, wiki, stars, and watchers automatically, and sets up an automatic redirect from the old URL to the new one. The main things that require deliberate handling are: the destination account must manually accept an email invitation within 24 hours (no CLI shortcut exists for this step), the local git remote needs a manual update afterward, and the old URL's redirect will permanently break if anyone ever creates a new repo named `six-degrees-kdot` under `jorelsantos-um` again.

**Product Contract preservation:** No origin document exists; this plan originates from a `ce-plan-bootstrap` session with the user (scope confirmed via the Phase 0.7 scoping synthesis, including resolving how to handle the previously-open PR #16 — it has since been merged into `main` in this same session, so it is no longer a live consideration for the transfer).

---

## Problem Frame

The user wants clean personal ownership of a project they're restarting, without losing any of its history (commits, merged PR #16, issue tracker, stars) or breaking their own ability to keep working on it locally. This is a GitHub account-administration task with real irreversibility characteristics (a completed transfer is not a one-click undo — reversing it means transferring back) and real access-control risk (get the destination account wrong, or lose track of which `gh` identity is active, and pushes/administration could go to the wrong place). The user explicitly asked for this to be done carefully and with verification at each step, not rushed.

This plan covers only the ownership transfer itself — initiating it, accepting it, updating local tooling to point at the new location, and verifying nothing was lost. It does not cover any other repo-management changes.

---

## Requirements

- **R1.** Transfer `six-degrees-kdot` from `jorelsantos-um` to `jorelsantos` using GitHub's native ownership-transfer mechanism, preserving full history (commits, merged PRs, issues, stars, wiki).
- **R2.** Verify, before initiating, that no blocking condition exists (naming conflict at the destination, unclean local state, unexpected repo configuration that transfer wouldn't handle cleanly).
- **R3.** Complete the destination-side acceptance step so the transfer actually finalizes (not left in a pending-invitation state).
- **R4.** Update the local git remote to point at the new repository location so the user's existing local clone keeps working without requiring a fresh `git clone`.
- **R5.** Verify after the transfer that the repo is fully reachable and intact from the personal account — correct owner, correct commit history, correct PR/issue history, old URL redirecting correctly.
- **R6.** Avoid the specific footgun GitHub's docs flag: never create a new repository named `six-degrees-kdot` under `jorelsantos-um` after the transfer, since that would permanently and irreversibly break the old-URL redirect.
- **R7.** Once the transfer is confirmed complete, deliberately decide whether `jorelsantos-um`'s local `gh` credential still needs `repo`-level access now that it no longer owns this repository, rather than leaving a stale admin-scoped token unaddressed by default.

---

## Key Technical Decisions

**KTD1 — Use GitHub's native web-UI transfer flow, not the raw REST API.**
GitHub exposes both a guided web UI (Settings → Danger Zone → Transfer ownership, which requires typing the repository name to confirm) and a raw `POST /repos/{owner}/{repo}/transfer` REST endpoint. For a one-time operation the user explicitly wants done with "no mistakes," the UI's typed-confirmation safeguard is worth the manual click over scripting it through `gh api` — this is exactly the kind of hard-to-reverse, access-affecting action that should not be silently automated. The UI is also where the user will need to be anyway to accept the transfer on the destination side (KTD2), so there's no automation time saved by scripting the initiation step separately.

**KTD2 — Treat destination-side acceptance as a manual, time-boxed user step.**
GitHub's docs confirm that transferring to a personal-account destination sends an email invitation that must be accepted within 24 hours or it expires — there is no documented `gh` CLI or REST API affordance to accept a transfer invitation programmatically. This plan sequences U2 (initiate) and U3 (accept) as adjacent steps specifically so the 24-hour window isn't put at risk by other work happening in between.

**KTD3 — Update the local remote only after the transfer is confirmed complete, not preemptively.**
GitHub's automatic old-URL redirect means `git fetch`/`git push` against the old `jorelsantos-um` URL keeps working transparently during the in-between period. Changing the local remote before the transfer finishes would just add a step to undo if something goes wrong at U2/U3. Updating it after (U4) means the remote change only happens once, against a known-good end state.

**KTD4 — Fallback path if native transfer is blocked: clone-and-recreate, not forced through.**
`jorelsantos-um`'s account type is a normal personal User account (confirmed via `gh api users/jorelsantos-um`), not an Enterprise Managed User account (which would show as an oddly-suffixed username and typically cannot interact with resources outside its enterprise at all) — so a hard block from school-account policy is unlikely. But if the transfer UI does refuse the operation (e.g., an undisclosed institutional GitHub policy), the safe fallback is: create a new empty repo at `jorelsantos/six-degrees-kdot`, push all branches and tags there via `git push --mirror`, and treat the old repo as archived rather than force through an unsupported transfer. This loses native issue/PR/star history (a real downgrade from R1) but avoids fighting a policy restriction outside the user's control. This plan's Implementation Units assume the native transfer path (KTD1) succeeds; the fallback is documented here as a contingency, not built out step-by-step, since it only activates if U2 fails.

---

## Implementation Units

### U1. Pre-transfer verification

**Goal:** Confirm every precondition holds true immediately before initiating the transfer, so U2 isn't started against stale assumptions.

**Requirements:** R2

**Dependencies:** None

**Files:** None (verification-only unit; no repo files change).

**Approach:** Re-check, at execution time (not relying on earlier-session findings, since state can drift):
- `gh auth status` shows `jorelsantos-um` as the active account with `repo` scope, and `jorelsantos` is also authenticated locally (needed for U3/U5).
- `gh api users/jorelsantos/repos` still shows no existing repository named `six-degrees-kdot` (destination naming-conflict check).
- Local `main` has no uncommitted changes and matches `origin/main` exactly (`git status` clean, `git rev-parse main` equals `git rev-parse origin/main`).
- `gh pr list --state open` on the repo returns zero results (confirms no open PRs are being carried into the transfer unexpectedly).
- Repo configuration is still as previously observed: zero webhooks, no GitHub Pages site, zero Actions secrets, no branch protection on `main` — if any of these are now non-zero, stop and re-assess before proceeding, since they'd need explicit handling this plan doesn't cover.

**Test scenarios:**
- Test expectation: none -- this unit is a verification checklist, not code; each check either passes (proceed to U2) or fails (halt and surface the specific mismatch to the user rather than guessing).

**Verification:** All five checklist items above are confirmed true in the same session immediately before U2 begins.

---

### U2. Initiate the transfer

**Goal:** Start the ownership transfer from `jorelsantos-um` to `jorelsantos` via GitHub's web UI.

**Requirements:** R1

**Dependencies:** U1

**Files:** None (GitHub account administration, not a repo file change).

**Approach:** Before opening Settings, confirm the browser is logged into github.com as `jorelsantos-um` — not `jorelsantos` or any other session — by checking the account avatar/username in the top-right nav. This check exists specifically because the plan's central risk is initiating an admin action from the wrong account context, and this is the one step where that mistake is otherwise unrecoverable-by-verification (a transfer initiated from the wrong account wouldn't fail loudly). Then navigate to `github.com/jorelsantos-um/six-degrees-kdot/settings` → Danger Zone → "Transfer ownership." Enter `jorelsantos` as the new owner and type the repository name (`six-degrees-kdot`) to confirm, per KTD1. This step must be performed by the user directly in the browser while authenticated as `jorelsantos-um` — it is not something `gh` CLI automation should attempt (KTD1).

**Test scenarios:**
- Test expectation: none -- one-time administrative action with no code path to test; correctness is verified by U3/U5's outcome checks instead.

**Verification:** GitHub shows a pending-transfer confirmation (repo settings will indicate the transfer is awaiting acceptance), and an invitation email/notification is sent to the `jorelsantos` account.

---

### U3. Accept the transfer on the personal account

**Goal:** Complete the transfer by accepting the invitation from the `jorelsantos` account before the 24-hour window expires (KTD2).

**Requirements:** R3

**Dependencies:** U2

**Files:** None.

**Approach:** Log in as `jorelsantos` (in browser, or via the email invitation link) and accept the transfer. Do this promptly after U2 rather than deferring, since the invitation expires after one day per GitHub's documented behavior.

**Test scenarios:**
- Test expectation: none -- manual acceptance step, no code involved.

**Verification:** `gh api repos/jorelsantos/six-degrees-kdot --jq '.owner.login'` returns `jorelsantos` (run this from a `gh` session authenticated as either account, since the repo is public).

---

### U4. Update local git remote and default `gh` account context

**Goal:** Point the existing local clone at the new repository location so ongoing work doesn't require a fresh `git clone`, and make sure future `gh`/`git` operations in this directory use the correct account.

**Requirements:** R4

**Dependencies:** U3

**Files:** None (local git configuration change, not a tracked repo file).

**Approach:**
- Run `git remote set-url origin https://github.com/jorelsantos/six-degrees-kdot.git`.
- Confirm `git fetch origin` and a no-op `git push` (or `git push --dry-run`) succeed against the new URL.
- Before switching, check for other local clones of `jorelsantos-um`-owned repos on this machine (e.g., `gh api users/jorelsantos-um/repos --jq '.[].name'` cross-referenced against known local project directories — `jorelsantos-um` owns at least `649_Altair` and `jorelsantos.github.io` in addition to this repo). If any exist and are actively worked on, note that this global switch will affect them too.
- Switch the active `gh` account to `jorelsantos` (`gh auth switch --user jorelsantos`) for continued work in this repo, mirroring the account-switching pattern already used earlier in this session when the wrong account blocked a push. This is a global default-account switch, not per-repo — any other local `jorelsantos-um` repo checked above will silently start using the `jorelsantos` identity for `gh` operations too, until switched back with `gh auth switch --user jorelsantos-um`.

**Test scenarios:**
- Test expectation: none -- git/gh configuration change; correctness is verified functionally (fetch/push succeed) rather than via automated tests.

**Verification:** `git remote -v` shows the new `jorelsantos` URL for `origin`; a `git fetch origin` succeeds with no errors; `gh auth status` shows `jorelsantos` as the active account.

---

### U5. Post-transfer integrity verification

**Goal:** Confirm the transfer preserved everything it should have, and that the old-URL redirect works — with an explicit guard against the redirect-breaking footgun (R6).

**Requirements:** R5, R6

**Dependencies:** U3 (verification can happen before or in parallel with U4, since it's checking the transfer itself, not the local remote)

**Files:** None.

**Approach:**
- Confirm commit history integrity: `git log --oneline -5` against the new remote shows the same commits as before the transfer, with `main` at the same SHA that was verified in this session prior to starting the transfer (`81b870f`, the PR #16 merge commit).
- Confirm merged PR #16 is still visible and intact at the new location: `gh pr view 16 --repo jorelsantos/six-degrees-kdot` should show the same title, merge status, and commit history as it did at the old location.
- Confirm the old URL redirects rather than 404s: `curl -sI https://github.com/jorelsantos-um/six-degrees-kdot` (or `git ls-remote https://github.com/jorelsantos-um/six-degrees-kdot.git`) resolves successfully via redirect rather than erroring.
- Explicitly document, for the user's own future reference, the R6 guardrail: do not create a new repository named `six-degrees-kdot` under `jorelsantos-um` — doing so at any point in the future would permanently sever the redirect GitHub just set up.

**Test scenarios:**
- Test expectation: none -- verification-only unit confirming a completed administrative action, not new code.

**Verification:** All four checks above pass. If the commit SHA or PR #16 state doesn't match pre-transfer, treat this as a genuine blocker and stop rather than proceeding to declare the transfer done.

---

### U6. Review `jorelsantos-um`'s residual credential access

**Goal:** Deliberately decide what to do with `jorelsantos-um`'s local `gh` token now that it no longer has a reason to hold `repo`-scoped admin access to this repository, rather than leaving a stale elevated credential unaddressed.

**Requirements:** R7

**Dependencies:** U5

**Files:** None.

**Approach:** After U5 confirms the transfer is complete and intact, decide — this is a judgment call for the user, not a default action — whether to revoke or downscope `jorelsantos-um`'s local `gh` credential (`gh auth logout --hostname github.com --user jorelsantos-um`, or narrow its token scopes on GitHub's Settings → Developer settings page) now that its admin justification for this specific repo is gone. Note that `jorelsantos-um` still legitimately owns other repos (e.g., `649_Altair`, `jorelsantos.github.io`, per U4's check) and may still need broad access for those — so this is about confirming the decision is intentional, not defaulting to revocation. A stale admin-scoped token is also the credential most likely to be used, by accident, to commit the exact R6 footgun (recreating `six-degrees-kdot` under `jorelsantos-um`).

**Test scenarios:**
- Test expectation: none -- credential-hygiene decision, not code.

**Verification:** The user has made and recorded an explicit choice (keep as-is, downscope, or revoke) rather than leaving it undecided by default.

---

## Scope Boundaries

**In scope:** The ownership transfer itself (initiation, acceptance, local remote update, integrity verification), and the specific pre-flight checks needed to do it safely.

**Out of scope (non-goals for this plan):**
- Any change to repo visibility, branch protection, or collaborator list beyond what the transfer itself changes by default.
- Re-granting `jorelsantos-um` any access to the repo after transfer (GitHub does not do this automatically, and this plan does not add it — if the user wants the school account to retain read access later, that's a separate, explicit decision).
- Any changes to the `casmlab` or `umsi-class` org memberships themselves.
- Broader `gh`/git multi-account workflow tooling (e.g., per-directory account switching via `.gitconfig` includeIf) — U4 handles this specific repo's remote and active account, not a general-purpose solution.

### Deferred to Follow-Up Work
- If the native transfer (U2) is blocked by an undisclosed institutional policy, execute the KTD4 fallback (clone-and-recreate via `git push --mirror`) as a separate, explicitly-scoped follow-up rather than an in-flight pivot of this plan.

---

## Risks & Dependencies

- **Risk: 24-hour acceptance window lapses (U2 → U3).** If the invitation expires before `jorelsantos` accepts, the transfer must be re-initiated from U2. Mitigation: KTD2 sequences U2 and U3 to happen back-to-back in the same working session.
- **Risk: institutional account restriction blocks the transfer.** Low likelihood per KTD4's reasoning (normal personal User account, not Enterprise Managed User), but not zero — some university-managed GitHub accounts carry non-obvious admin-side restrictions. Mitigation: KTD4 fallback path, only invoked if U2 actually fails.
- **Risk: accidentally recreating a repo at the old name (R6).** No enforcement exists to prevent this — it depends on the user (or a future agent session) remembering not to. Mitigation: called out explicitly in U5 and in this plan's Scope Boundaries as a standing guardrail, not just a one-time check.
- **Dependency: both `jorelsantos-um` and `jorelsantos` GitHub accounts must remain accessible for the duration of U1–U5.** Both are already authenticated locally via `gh auth status` as of this planning session.
- **Risk: `gh auth switch` in U4 is a global default-account change, not per-repo.** `jorelsantos-um` owns other local-clone repos (e.g., `649_Altair`, `jorelsantos.github.io`) that would silently start using the `jorelsantos` identity for `gh` operations after U4, until manually switched back. Mitigation: U4 now checks for other local `jorelsantos-um` clones before switching.
- **Risk: wrong browser account context when clicking "Transfer ownership" in U2.** A transfer initiated from the wrong logged-in account wouldn't fail loudly. Mitigation: U2 now requires an explicit account check in the browser immediately before opening the transfer dialog.

---

## Verification Contract

- `gh api repos/jorelsantos/six-degrees-kdot --jq '.owner.login'` returns `jorelsantos`.
- Local `origin` remote points at `https://github.com/jorelsantos/six-degrees-kdot.git` and `git fetch origin` succeeds.
- `main` at the new location is at the same commit SHA verified before the transfer began.
- PR #16's history (title, merge status, commit list) is intact at the new location.
- The old URL (`github.com/jorelsantos-um/six-degrees-kdot`) redirects rather than 404s, and no new repository has been created there.

## Definition of Done

- [ ] Pre-transfer checklist confirmed clean (U1)
- [ ] Transfer initiated from `jorelsantos-um` (U2)
- [ ] Transfer accepted from `jorelsantos` within the 24-hour window (U3)
- [ ] Local remote and active `gh` account updated (U4)
- [ ] Post-transfer integrity verified: history, PR #16, and old-URL redirect all intact (U5)
- [ ] `jorelsantos-um`'s residual credential access explicitly reviewed and decided (U6)
