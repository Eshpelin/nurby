# UX-army findings ledger

Continuous agentic user testing. Each run role-plays one persona from
`testing/personas/` through the real product in a browser, logs what it
hits here, fixes what it can, and hands the rest to the next run.
Run reports live in `testing/runs/`. Numbering continues from the
2026-07-12 overnight review (F1-F65 in `docs/ux-review-2026-07-12.md`),
so the first army finding is F66.

Entry format:

```
F<id> | severity(blocker/major/minor/polish) | persona | area | status(open/fixed/deferred-feature)
  What: one-sentence defect from the user's point of view.
  Repro: steps.
  Fix: commit sha or backlog reason.
```

## Open backlog

F70 | minor | margaret-retired-teacher | frontend/add-camera | open
  What: in Add Camera the Name field's placeholder is "Front Door" —
  a plausible real answer, not an example — so it reads as already
  filled in, while the submit button is disabled under the hint "Enter
  a Name above to continue." A low-tech user sees a field that says
  "Front Door" and a button insisting she enter a name.
  Repro: dashboard → checklist "Add your own camera" → look at Name.
  Fix: pending. Suggest a placeholder that can't be mistaken for a
  value (e.g. "e.g. Front Door"), matching how Stream URL's placeholder
  is obviously an example.

F71 | polish | margaret-retired-teacher | frontend/add-camera | open
  What: "Don't know your camera's URL? Pick your brand" opens a grid of
  ~25 brands with no search box and no "I don't know / help me find it"
  escape. It only helps a user who already knows their brand — but the
  users who don't know their URL are disproportionately the ones who
  didn't install the camera themselves (Margaret's daughter mounted
  hers and left).
  Repro: Add Camera → Stream URL → Pick your brand → scroll.
  Fix: pending. Suggest a filter box plus a fallback pointing at the
  Scan Network tab, which already solves exactly this case but is not
  referenced from here.

## Deferred features

Findings that need multi-day feature work, with the reason. Runs pick
these up before starting new persona flows once the open backlog is empty.

(none yet)

## Fixed

F68 | blocker | margaret-retired-teacher | harness | fixed
  What: no camera could ever come online and no detection was ever
  produced, on any run, for any persona. The dashboard just said
  "Nothing happened yet" and "Some cameras are offline. Check their
  stream URLs or credentials" forever. This silently made the core of
  the product — did anyone come to the door, did a rule fire, who was
  here yesterday — untestable for every persona in the rotation.
  Repro: add a camera pointed at a harness feed, wait: status stays
  "offline", /api/observations stays empty.
  Root cause: `docker compose config --services` defines `ingestion`
  and `perception`, but start_stack.sh only ever started `postgres
  redis mediamtx` plus the API. Nothing consumed the RTSP feeds. The
  compose definitions couldn't be used as-is either: they hardcode the
  `nurby` database and resolve peers by compose service name
  (postgres:5432, rtsp://mediamtx:8554), none of which points at the
  uxtest stack, and rtsp://localhost:8554/... (what a persona actually
  types into Add Camera) does not resolve from inside a container.
  Fix: run both on the host from .venv-test, like the API already is,
  with uxtest DB/Redis/media-path env. Verified: Front Door reaches
  "recording", perception logs "Detections ... person", and the
  dashboard digest reports "Activity was recorded on Demo Camera,
  Front Door. Detections included car, person, bicycle." commit
  (this run; see git log).

F69 | major | margaret-retired-teacher | harness | fixed
  What: uxtest perception wrote observations for cameras that don't
  exist in nurby_uxtest — `Living Room` and `Backyard`, which are rows
  in the main `nurby` dev database.
  Repro: run perception against nurby_uxtest while the main dev stack
  has previously run; watch it log keyframes for foreign camera ids.
  Root cause: motion keyframes travel over the Redis STREAM
  `nurby:motion`, and both stacks defaulted to redis://localhost:6379/0.
  Streams persist, so uxtest perception woke up and replayed the dev
  stack's leftover backlog into the uxtest DB.
  Fix: pin the whole uxtest stack (API, ingestion, perception) to its
  own Redis index, redis://localhost:6379/1. Verified: perception now
  only logs the two uxtest camera ids. commit (this run; see git log).

F66 | blocker | kevin-impatient-exec | infra/migrations | fixed
  What: `alembic upgrade head` reported success and printed every
  migration as applied, but nothing persisted: a fresh database ended up
  with zero tables. Every API request 500'd (`relation "users" does not
  exist`), and the frontend's fresh-install auto-bootstrap silently
  swallowed the 500 and fell back to a login wall for an account that
  could never exist, so a first-time user was stuck with no way in.
  Repro: fresh `nurby_uxtest` DB, run `alembic upgrade head`, then
  `\dt` in psql shows no relations.
  Root cause: `alembic/env.py` ran migrations inside `async with
  connectable.connect()`. Under SQLAlchemy 2.0's async engine, `.connect()`
  autobegins a transaction but nothing commits it, so closing the
  connection issues an implicit ROLLBACK and every DDL statement in the
  migration chain is silently undone.
  Fix: use `connectable.begin()` instead of `.connect()` so the
  transaction commits on a clean exit. commit 36483aa.

F67 | blocker | kevin-impatient-exec | frontend/auth | fixed
  What: after fresh login (or the auto-bootstrap flow), several core
  surfaces permanently 401'd forever: the notification bell count, the
  AI-provider health badge in the navbar, and the dashboard's camera
  list. Concretely, the "Show me some magic" one-click onboarding wizard
  got stuck forever on "Starting download of <model>" with a Cancel
  button that never resolved anything, because the same bug also killed
  its poll-for-progress loop. Confirmed via the network log: zero
  `/api/ollama/deploy/status` polls were ever sent despite 35+ seconds
  elapsed, while the backend job had already settled into a terminal
  `error` stage within a second.
  Repro: hit `/` on a fresh install so the auto-bootstrap effect fires
  after mount, watch `/api/cameras`, `/api/providers`, `/api/providers/health`,
  `/api/notifications/count` 401 on every poll cycle indefinitely.
  Root cause: `frontend/src/lib/auth.tsx`'s `authFetch` closed over the
  `token` state value directly, so its function identity changed every
  time `token` changed. Multiple call sites across the app
  (`navbar.tsx`'s `fetchProvider`/`fetchUnreadCount`, `page.tsx`'s
  `fetchCameras`, and others) wrapped their own fetch logic in
  `useCallback(..., [])` with an empty dependency array, freezing
  whichever `authFetch` existed at first mount. On a fresh page load
  that first mount happens before the token is hydrated from
  localStorage (or before bootstrap issues one), so those closures
  permanently held an unauthenticated `authFetch` and never picked up
  the real token, even after login succeeded.
  Fix: `authFetch` now reads the token through a ref (`tokenRef`,
  kept in sync via a `useEffect` on `token`) instead of the `token`
  closure variable, so its own identity is stable and every caller —
  stale-closure or not — always sends the current token. commit
  432764f.

## Working well

Positive confirmations, so "what works" is data too. One line each:
persona, flow, date.

- kevin-impatient-exec, 2026-07-16: auto-bootstrap drops a fresh visitor
  straight onto the dashboard with a real onboarding modal, no signup
  form, once the underlying DB/auth bugs (F66/F67) were fixed.
- kevin-impatient-exec, 2026-07-16: "Do it all for me" magic setup adds
  a demo camera and gracefully degrades to "no local model, here's a
  one-command fix" instead of pretending success when the model pull
  fails.
- kevin-impatient-exec, 2026-07-16: "Secure your account" flow is
  genuinely one-click-ish — pre-filled name, three fields, one submit.
- kevin-impatient-exec, 2026-07-16: dashboard answers "did anything
  happen today?" directly on load with no navigation required.
  RETRACTED 2026-07-17: the honest "Nothing happened yet" Kevin saw was
  only honest by accident — nothing had happened because the harness
  never ran ingestion/perception at all (F68). The layout claim still
  holds; the "it correctly reports quiet periods" implication doesn't,
  and is now genuinely testable for the first time.
- margaret-retired-teacher, 2026-07-17: with F68 fixed, the dashboard
  earns that claim properly — the wall shows Front Door REC at
  1280x720/15fps, the digest names real detections ("car, person,
  bicycle"), and the timeline attributes "Person seen 1×" to the right
  camera, all without configuring any AI provider. Matches the
  "detection works without AI" promise the banner makes.
