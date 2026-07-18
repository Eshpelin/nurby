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

Also noted, not filed as its own F#: the Invite Keys panel
(Settings → Invite Keys → Manage) lists each key's role/uses/expiry
but not which cameras it grants, so an audit-minded admin can't tell
a key's scope from the list without re-testing it. Minor; pick up
alongside F76 or standalone.

## Deferred features

Findings that need multi-day feature work, with the reason. Runs pick
these up before starting new persona flows once the open backlog is empty.

(none yet)

## Fixed

F76 | minor | priya-landlord | frontend/dashboard | fixed
  What: dashboard wall toolbar's "+ Camera" / "+ Widget" buttons were
  intermittently unclickable — real mouse clicks missed 3/3 times in
  the priya-landlord run. Root cause: the left dashboard column
  (`app/page.tsx:1534`) had no overflow handling, so when
  `SetupChecklistCard`/`AskComposerCard` above it consumed the
  viewport's available height, `CameraWall`'s toolbar row visually
  spilled below its own box into the same screen region as
  `SystemHealthFooter`, which won the hit-test since it's later in the
  DOM.
  Fix: `app/page.tsx:1534` left column gained `lg:overflow-y-auto`, so
  when its content exceeds the available height the column scrolls
  instead of letting the toolbar spill into the footer's hit-test
  region. Verified: fresh Mei session, `elementFromPoint` at the
  "+ Camera" button's own bounding-rect center now returns the button
  itself, and clicking it via ref opens the Add Camera modal. commit
  3a56b72.

F75 | major | priya-landlord | frontend/security-ux | fixed
  What: revoking a user's ONLY camera grant in Settings → Camera
  access didn't restrict them further — the product's own documented
  policy (zero grants = sees all cameras) means it flipped them back
  to seeing every camera, the opposite of what "revoke" reads as. An
  admin trying to lock a tenant out by toggling off their last camera
  would silently grant them everyone else's cameras instead.
  Repro: grant a viewer exactly one camera, then revoke it; the panel
  now reads "No grants · this user currently sees all cameras."
  Fix: `frontend/src/app/settings/access/page.tsx` confirms before
  toggling off a user's last grant, naming the camera, the user, and
  stating plainly they'll see all N cameras instead of none. Verified
  by stubbing `window.confirm` to inspect the message and cancel, then
  confirming the grant was untouched. commit (this run; see git log).

F74 | major | priya-landlord | product/security | fixed
  What: the Morning Brief digest served the same household-wide
  cached row to every user regardless of camera-access grants. A
  viewer restricted to one camera still saw brief bullets naming other
  cameras by name ("Demo Camera", "Front Door") they have no grant to.
  Reproduced fresh (not a stale-cache artifact) by regenerating the
  brief as the restricted user.
  Root cause: `services/perception/daily_digest.py`'s
  `_collect_facts()`/`build_daily_digest()` had no camera filter and
  no per-user concept — one global digest, unlike every other
  camera-scoped read surface.
  Fix: `_collect_facts()` gained an optional `camera_ids` filter
  applied to observations/incidents/audio/conversations/camera-name
  lookup; vehicles and journeys are cross-camera by nature and are
  omitted (not filtered) for a scoped digest to avoid leaking through
  them. `services/api/routes/daily_digest.py`'s three routes now
  branch on `allowed_camera_ids`: unrestricted/admin callers get the
  existing persisted household digest unchanged (verified no
  regression as an admin), restricted callers get a fresh unpersisted
  facts-only digest scoped to their grants. commit (this run; see git
  log).

F73 | blocker | priya-landlord | api/security | fixed
  What: `/api/incidents` (list, single-get, reinterpret) had zero
  camera-access-grant filtering, unlike every other scoped endpoint.
  A restricted viewer could see incident rows — including full
  observation-id lists and thumbnail file paths — from cameras outside
  their grant via the list endpoint, and could fetch or reinterpret
  ANY incident by UUID regardless of scope via the single-get/
  reinterpret endpoints (no ownership check existed at all).
  Repro: grant a viewer one camera, hit `/api/incidents` as them,
  observe camera_ids belonging to other cameras in the response.
  Fix: `services/api/routes/incidents.py` now uses the same
  `allowed_camera_ids`/`apply_camera_filter` helper as
  `observations.py`/`cameras.py`/`events.py`/`recordings.py`. Added
  `_get_incident_in_scope()`, shared by the single-get and reinterpret
  routes, which 404s (not 403, to avoid confirming existence) for
  incidents outside the caller's grant. Verified: as the restricted
  viewer, `/api/incidents` now only returns rows for their granted
  camera id. commit (this run; see git log).

F71 | polish | margaret-retired-teacher | frontend/add-camera | fixed
  What: NOT "asking for a stream URL is bad" — asking is fine and
  normal. The narrow point: the product already decided the raw URL is
  a barrier for some users, which is why it ships both a brand picker
  and a Scan Network tab. But the brand picker — the escape hatch —
  opened a ~25-item grid with no filter box and no "I don't know my
  brand" path, and never mentioned Scan Network, which is the thing that
  would actually solve it. So the one affordance built for the
  don't-know-my-URL user dead-ended for the subset who also didn't know
  the brand (didn't install the camera themselves).
  Repro: Add Camera → Stream URL → Pick your brand → scroll.
  Fix: `CameraBrandHelp.tsx` gained a filter textbox above the brand
  chips (filters by name, shows "No brands match" on empty), and the
  no-brand-selected copy now reads "Not listed, or don't know which
  brand you have? Scan your network instead" as a button that switches
  `AddCameraModal`'s tab to Scan Network. commit 86b1aa3
  (steve-diy-tinkerer run, 2026-07-18).

F72 | major | margaret-retired-teacher | product/observability | fixed
  What: the PRODUCT half of F68, and the more important half. With a
  background worker stopped, nothing anywhere said so. The dashboard
  said "Nothing happened yet" — indistinguishable from a quiet day —
  and, worse, "Some cameras are offline. Check their stream URLs or
  credentials", actively sending the user to debug a camera that was
  perfectly fine. The System doctor, whose entire job is answering "why
  isn't this working?", had no check for ingestion or perception at
  all: it reported the camera as the failure and told the user to
  verify the stream path and credentials. A dead worker and a broken
  camera were indistinguishable from every surface.
  Repro: stop ingestion, load the dashboard, run the doctor. Nothing
  mentions the worker; everything blames the camera.
  Root cause: nothing ever asked whether the workers were alive.
  camera.status is maintained BY ingestion, so with ingestion dead it's
  just a stale row that the doctor read as fact.
  Fix: `shared/heartbeat.py` — each worker writes a TTL key to Redis on
  a timer, so a crashed OR hung worker stops beating and reads as down,
  with no clock math. Doctor gains "Video ingestion" / "AI perception"
  checks, listed first because a dead worker causes most of what
  follows. The camera check now takes ingestion liveness and, when it's
  down, warns that the camera's status is stale instead of blaming the
  user's credentials. /api/system/health carries worker state on the
  poll the footer already makes, and the dashboard shows a real banner
  plus an honest "Nothing is running" empty state.
  Credit: spotted by the user, who asked the right question about F68 —
  "if the services aren't up there should be an error, right? It
  shouldn't just say nothing happened yet." I had only fixed the
  harness and missed that the product had the same blind spot.
  commit (this run; see git log).

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
- steve-diy-tinkerer, 2026-07-18: a deliberately wrong RTSP URL is
  caught by the connect-test before saving, naming the exact
  unreachable IP:port with a plain-English cause and fix hint, plus an
  explicit "submit again to add anyway" escape hatch for cameras that
  are just temporarily off.
- steve-diy-tinkerer, 2026-07-18: System doctor's "Run checks" breaks
  results down per-service (ingestion, perception, DB, Redis, relay,
  email, alert delivery, disk) AND per-camera, each with a millisecond
  timing, so a diagnostics-minded user can see exactly which piece is
  broken instead of inferring it from one offline camera row.
- steve-diy-tinkerer, 2026-07-18: raw-RTSP camera add reached live
  detections (person 88-93% confidence) in under a minute end to end.
- steve-diy-tinkerer, 2026-07-18: ONVIF Scan Network gives an honest,
  specific "no ONVIF cameras found" message with troubleshooting steps
  rather than hanging or silently returning empty.
