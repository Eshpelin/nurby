---
name: user-army
description: Execute one persona-driven UX test run against the local Nurby stack - boot harness, role-play the next persona in the browser, log findings, fix everything found, commit, advance the cursor. Invoked by the ux-army scheduled task or manually via /user-army.
---

# User-army run protocol

One invocation = one complete run: deploy the latest repo fresh, fix the
inherited backlog, live one persona's session in the browser, log
findings, fix them, commit, advance. Designed to be killed at any point
and resumed by the next scheduled run, so commit state early and often.

Run fully autonomously. Never stop to ask for approval, confirmation, or
a decision — there is no human watching a scheduled run. Make the
reasonable call, note it in the run report, and keep going. The only
thing that ends a run early is a stack that will not boot (see Budget
rules), and even that ends with a committed blocker finding, not a
question.

## 0. Preflight — fresh worktree + net-new deploy

The run works in a dedicated worktree checked out to the latest
`origin/main`, never in the primary checkout. That way whatever
uncommitted work is sitting in the primary checkout can never block or
get clobbered, and the deploy always exercises the current committed
code — which also tests that deployment itself still works.

1. `cd /Users/ahmed.anough/Desktop/nurby-backend`
2. `git fetch origin`.
3. Prepare the persistent ux-army worktree at
   `/Users/ahmed.anough/.claude/worktrees/ux-army`:
   - If it does not exist:
     `git worktree add -B ux-army /Users/ahmed.anough/.claude/worktrees/ux-army origin/main`
   - If it exists, refresh it to latest without touching local
     bookkeeping: `cd` into it, then
     `git fetch origin && git reset --hard origin/main && git clean -fd`.
     Use `git clean -fd`, **never** `-x`: the run bookkeeping
     (`testing/state.json`, `testing/FINDINGS.md`, `testing/runs/`,
     `testing/harness/users.md`) is gitignored and lives only in this
     worktree; `-x` would wipe it and lose the resume trail.
   - Do the rest of the run from inside this worktree.
4. If the worktree is brand new (no `testing/state.json` in it yet),
   seed its bookkeeping once from the primary checkout:
   `cp /Users/ahmed.anough/Desktop/nurby-backend/testing/state.json .`
   and likewise `testing/FINDINGS.md`, `testing/runs/`,
   `testing/harness/users.md` if present. After the first run the
   worktree owns them.
5. Net-new deploy from the worktree:
   `testing/harness/start_stack.sh --fresh`. This tears the compose
   stack down, rebuilds its images, drops and re-migrates nurby_uxtest,
   and restarts the host API/ingestion/perception on the current code
   (docker deps, nurby_uxtest DB, API :8787, RTSP loop at
   `rtsp://localhost:8554/uxcam`). Treat a deploy failure as a first-
   class finding: if `--fresh` cannot bring the stack up, that is a
   deployment regression worth logging, fixing if quick, or deferring.
6. Start the frontend with the preview tool (`preview_start` name
   `frontend`, port 3210, already pointed at :8787). The preview builds
   from the worktree's frontend, so it too runs latest code.
7. Read `testing/state.json`, `testing/FINDINGS.md`, and the persona file
   `testing/personas/<order[cursor]>.md`. Read the persona's most recent
   report in `testing/runs/` if one exists, to avoid repeating goals.
8. Every persona already has a real login — check
   `testing/harness/users.md` for the email/password before doing
   anything else. Just log in as the persona whose turn it is; don't
   register or hunt for an invite key. (All 20 were seeded in one batch
   via `testing/harness/seed_persona_accounts.py` on 2026-07-17, after
   the first run's persona hit a login screen for an account that
   didn't exist yet. If `users.md` is ever missing a persona for some
   reason, re-run that script — it's idempotent — before falling back
   to the invite flow.)

## 1. Inherited backlog first

Fix policy is fix-everything. Before any new browsing, work the "Open
backlog" section of FINDINGS.md, then "Deferred features" top-down.
Each item: fix, verify in the browser, move to "Fixed" with the commit
sha, commit. If an item truly needs multi-day feature work, leave it in
"Deferred features" with one sentence on what unblocks it.

## 2. Persona session in the browser

Role-play, do not audit. You ARE the persona: their tech level, their
patience, their vocabulary. Use only what a user can see: no API calls,
no source peeking, no URL surgery (unless the persona would, like Tom).
Type realistic data at realistic speed. When the persona would give up,
give up, and that IS the finding.

- The DB is dropped and re-migrated on every run's fresh deploy, so it
  starts empty each time — but personas' logins in `users.md` are
  reseeded/persist, so a returning persona logs back into their account
  and rebuilds their cameras and rules as part of the session. Everyone
  logs into their pre-seeded account from `testing/harness/users.md` —
  no registration needed. Exception: if a persona's own goals include
  creating a *second* account for someone else (e.g. ahmed-remote-son
  inviting his mother as a guardian), that invite-and-claim flow is
  still exactly what you should test live; record whatever new
  credentials that produces in `users.md`.
- Navigate with `read_page` primarily; screenshot at judgment moments
  (first impressions, confusing screens, anything broken). Budget:
  roughly 50 browser interactions, one flow lived deeply beats five
  skimmed.
- Do NOT call `resize_window`. It breaks the pane's click-coordinate
  mapping: afterwards clicks land at a multiplied offset (measured 8x
  at 1280x800) and silently hit the wrong element or nothing at all,
  which reads exactly like a product bug and burns budget chasing it.
  Only the native size maps correctly. Prefer ref-based clicks from
  `read_page`; if you must use raw coordinates, they are in
  screenshot-pixel space (native pane: screenshot 640 wide = 320 CSS
  px, so coordinate = CSS x 2). The pane is ~320 CSS px wide, so
  personas are testing the mobile layout — judge it as such.
- Before trusting "the click did nothing", verify with a
  `javascript_tool` probe (e.g. `btn.click()`) before logging a
  finding. A real dead control reproduces both ways.
- Judge every step: unclear labels, missing affordances, dead ends,
  silent failures, missing feedback, ugly states, and also what works
  well.
- Cameras: pick the scene that matches the persona's story from
  `testing/harness/feeds.json` (looping RTSP paths like
  `rtsp://localhost:8554/front-door`, `.../pets`, `.../guardian-room`).
  Margaret gets a porch, Sofia gets a dog, Carlos gets vehicles: the
  feed must make the persona's rules plausibly fire. Each scene is a
  pool of clips that rotates between runs, so a returning persona's
  camera shows different footage than last time; that is intentional,
  treat it as a new day. Notable pools: `sidewalk` and `indoor-room`
  have visible faces for face-recognition flows; `guardian-room` has
  fall-detection positives (person ends on the floor) and normal
  daily-activity negatives; `lobby` includes bag-drop and fight clips
  for incident/alert flows. Name and describe the camera the way the
  persona would ("Front door", not "front-door feed").

## 3. Log findings (local only, never committed)

Write `testing/runs/YYYY-MM-DD-HHMM-<persona>.md`: persona, goals
attempted, step-by-step narrative with verdicts, findings list, what
worked. Then merge findings into `testing/FINDINGS.md`: dedupe against
every existing entry (including docs/ux-review-2026-07-12.md), continue
the F-numbering, put positives under "Working well".

These bookkeeping files (`testing/runs/`, `testing/FINDINGS.md`,
`testing/state.json`) are gitignored on purpose — they are a local
resume trail, not something the public repo needs. Do NOT try to commit
them, do NOT `git add -f` them, and do NOT treat their absence from a
commit as a problem. They persist between runs because the worktree is
persistent, not because they are in git. Save them to disk before
starting fixes so a dead session loses nothing, but there is no ledger
commit step anymore.

## 4. Fix everything found

For each new finding, severity order: reproduce, fix in source, verify
the fix in the browser as the persona, `npx tsc --noEmit` in frontend/
for frontend changes, targeted pytest for backend changes. Move the
entry to "Fixed" with the sha. Multi-day items go to "Deferred features"
with a reason. If the session is running long, committing verified fixes
beats starting new ones: never leave a half-applied fix uncommitted.

Commit ONLY product code — source, tests, migrations, harness scripts.
Because the bookkeeping is gitignored, a plain `git add -A && git commit`
will already exclude it; do not fight that. Prefix every commit
`ux-army:`. Push to `origin main` from the worktree
(`git push origin ux-army:main`, or fast-forward push the branch). If a
push is rejected because `origin/main` moved, `git fetch` and rebase the
worktree branch onto `origin/main`, then push again. Never force-push.

## 5. Close out

1. Update `testing/state.json`: cursor = (cursor+1) % len(order),
   runs_completed += 1, last_run ISO timestamp, last_run_persona. (This
   file is gitignored and stays in the worktree — updating it on disk is
   the whole point; there is nothing to commit for it.)
2. Ensure every verified product fix is committed and pushed to main.
   Leave no half-applied fix in the worktree.
3. Final message: persona, goals covered, findings found/fixed/deferred,
   one-line product verdict from the persona's mouth.

## Budget rules

Runs fire every 3h on a limited token plan. Hard rules: one persona per
run, no fix rabbit-holes past ~30 min without committing something,
prefer read_page over screenshots, never re-verify the whole app (only
what you touched). If the `--fresh` deploy fails to bring the stack up
after two repair attempts, that is itself the finding: record it in
`testing/FINDINGS.md` as a deployment blocker (on disk, local only),
make sure any product fix you did land is committed and pushed, and
stop. A broken deploy is a real result, not a reason to fall back to a
stale stack.
