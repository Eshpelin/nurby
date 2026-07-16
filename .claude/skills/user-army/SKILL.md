---
name: user-army
description: Execute one persona-driven UX test run against the local Nurby stack - boot harness, role-play the next persona in the browser, log findings, fix everything found, commit, advance the cursor. Invoked by the ux-army scheduled task or manually via /user-army.
---

# User-army run protocol

One invocation = one complete run: fix inherited backlog, live one
persona's session in the browser, log findings, fix them, commit,
advance. Designed to be killed at any point and resumed by the next
scheduled run, so commit state early and often.

## 0. Preflight

1. `cd /Users/ahmed.anough/Desktop/nurby-backend`
2. `git checkout main && git pull --ff-only`. If the tree is dirty with
   changes you did not make, stop and report instead of clobbering.
3. `testing/harness/start_stack.sh` (idempotent: docker deps, nurby_uxtest
   DB, API :8787, RTSP loop at `rtsp://localhost:8554/uxcam`).
4. Start the frontend with the preview tool (`preview_start` name
   `frontend`, port 3210, already pointed at :8787).
5. Read `testing/state.json`, `testing/FINDINGS.md`, and the persona file
   `testing/personas/<order[cursor]>.md`. Read the persona's most recent
   report in `testing/runs/` if one exists, to avoid repeating goals.
6. Credentials for existing test users are in `testing/harness/users.md`
   (create it on first run). First run ever: complete product setup as
   the admin persona. Later personas join via invite keys created by the
   admin account, which dogfoods the invite flow every time.

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

- The DB persists across runs on purpose: returning personas find their
  old cameras and rules; new personas register fresh via invite key.
  Record any new credentials in `testing/harness/users.md`.
- Navigate with `read_page` primarily; screenshot at judgment moments
  (first impressions, confusing screens, anything broken). Budget:
  roughly 50 browser interactions, one flow lived deeply beats five
  skimmed.
- Judge every step: unclear labels, missing affordances, dead ends,
  silent failures, missing feedback, ugly states, and also what works
  well.
- Cameras: pick the feed that matches the persona's scene from
  `testing/harness/feeds.json` (looping RTSP paths like
  `rtsp://localhost:8554/front-door`, `.../pets`, `.../indoor-room`).
  Margaret gets a porch, Sofia gets a dog, Carlos gets vehicles: the
  feed must make the persona's rules plausibly fire. Name and describe
  the camera the way the persona would ("Front door", not "front-door
  feed"). The `sidewalk` feed has visible faces for face-recognition
  flows.

## 3. Log findings

Write `testing/runs/YYYY-MM-DD-HHMM-<persona>.md`: persona, goals
attempted, step-by-step narrative with verdicts, findings list, what
worked. Then merge findings into `testing/FINDINGS.md`: dedupe against
every existing entry (including docs/ux-review-2026-07-12.md), continue
the F-numbering, put positives under "Working well". Commit the report
and ledger BEFORE starting fixes, so a dead session loses nothing.

## 4. Fix everything found

For each new finding, severity order: reproduce, fix in source, verify
the fix in the browser as the persona, `npx tsc --noEmit` in frontend/
for frontend changes, targeted pytest for backend changes. Move the
entry to "Fixed" with the sha. Multi-day items go to "Deferred features"
with a reason. If the session is running long, committing verified fixes
beats starting new ones: never leave a half-applied fix uncommitted.

## 5. Close out

1. Update `testing/state.json`: cursor = (cursor+1) % len(order),
   runs_completed += 1, last_run ISO timestamp, last_run_persona.
2. Commit everything remaining, prefix `ux-army:`, push to main.
3. Final message: persona, goals covered, findings found/fixed/deferred,
   one-line product verdict from the persona's mouth.

## Budget rules

Runs fire every 3h on a limited token plan. Hard rules: one persona per
run, no fix rabbit-holes past ~30 min without committing something,
prefer read_page over screenshots, never re-verify the whole app (only
what you touched). If the stack fails to boot after two repair attempts,
log it in FINDINGS.md as a blocker finding, commit and stop; broken
harness is itself a finding.
