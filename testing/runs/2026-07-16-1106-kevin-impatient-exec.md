# Run: kevin-impatient-exec — 2026-07-16

First-ever ux-army run (runs_completed was 0, empty backlog, no seeded
users). Kevin's persona: medium tech, zero patience, accepts every
default, clicks primary buttons instantly, dismisses everything else.

## Goals attempted

- Full setup in under 5 minutes accepting every default
- Whatever the dashboard nags him to do, do it in one click
- Glance at the timeline: "did anything happen today?"
- Turn off "the annoying notifications" fast

## Narrative

Opened `http://localhost:3210` fresh. Expected the documented
"never hit a signup wall" auto-bootstrap behavior. Instead landed on
a login form for an account that could never exist — **dead end**.
Traced it: `alembic upgrade head` printed every migration as applied
but the database ended up with zero tables. `alembic/env.py` ran
migrations inside `connectable.connect()`, which under SQLAlchemy
2.0's async engine autobegins a transaction that nothing commits, so
every DDL statement silently rolled back on close. Every API request
was 500ing (`relation "users" does not exist`), and the frontend's
bootstrap effect swallowed the 500 into a plain login wall. Fixed by
switching to `connectable.begin()` (commit 36483aa). This is a
blocker: it means every fresh install / fresh test DB never actually
gets a schema, silently.

With that fixed, Kevin loaded the real "Welcome to Nurby" modal and
clicked **"Do it all for me"** — one click, in character. It added a
demo camera fine, then tried to download the recommended local vision
model (`gemma4:12b`). The Ollama binary in this environment is too
old to pull that model (`412: requires a newer version of Ollama`).
That itself is an environment limitation, not a product bug — the
app's designed fallback path (retry with `gemma3:4b`, then give up
honestly and offer a manual `docker compose` command) is exactly the
right UX. But it never fired: the wizard sat on "Starting download of
gemma4:12b …" with a dead Cancel button for 35+ seconds while the
backend job had already failed and moved to a terminal `error` stage
within about a second. Network log showed zero
`/api/ollama/deploy/status` polls ever sent.

Root cause was bigger than the wizard: `authFetch` in `auth.tsx`
closed over the `token` state value, so several call sites across the
app (`navbar.tsx`'s provider/notification-count polling, the
dashboard's `fetchCameras`) had memoized their own fetch wrapper with
an empty `useCallback` dependency array, freezing whichever
`authFetch` existed at first mount — before the token hydrates. Those
frozen closures sent unauthenticated requests **forever**, confirmed
in the network log: `/api/cameras`, `/api/providers`,
`/api/providers/health`, `/api/notifications/count` 401'd on every
single poll cycle, indefinitely, after a perfectly successful login.
Fixed by having `authFetch` read the token through a ref instead, so
its identity (and every stale closure holding it) stays valid forever
(commit 432764f). Re-tested: the wizard now completes normally,
falls back to "no local model, here's a one-command fix" honestly,
and the notification/provider/camera polls stay 200 OK indefinitely
after the initial cold-load blip.

Kevin then clicked **"Secure your account"** off the dashboard nag,
filled name (pre-filled "Alex" — fine, not his name, but he didn't
notice or care)/email/password in one pass, submitted — worked
cleanly, banner cleared.

Glanced at the timeline for "did anything happen today?" — the
dashboard states "Nothing happened yet" directly on the main wall,
no digging required. Good, honest, fast answer.

Went looking for a quick way to "turn off the annoying notifications."
No Telegram/email channels were configured, so nothing was actually
notifying him yet, and no dedicated one-click global notification mute
surfaced in a scan of Settings. Not confirmed as a gap (didn't
exhaustively search every settings subsection under this run's time
budget) — noting for a future run to verify explicitly once
notifications are actually flowing.

## Findings

- F66 (blocker, fixed): alembic migrations silently no-op on fresh DBs.
- F67 (blocker, fixed): `authFetch` token goes permanently stale for
  callers that memoized it early, breaking notification/provider/camera
  polling and stalling the one-click onboarding wizard forever.

## What worked

- Auto-bootstrap (once the DB actually had tables) dropped Kevin
  straight onto the dashboard with a real onboarding modal — no
  signup form, matches the documented intent well.
- "Do it all for me" magic setup correctly added a demo camera and,
  once the polling bug was fixed, gracefully degraded to "no local
  model" with an honest one-command fix instead of pretending to
  succeed.
- "Secure your account" flow: pre-filled name, three fields, one
  submit, done. Genuinely one-click-ish for an impatient exec.
- Dashboard answers "did anything happen today?" directly on load,
  no navigation required.

## Kevin's verdict

"Fine once it actually worked — but I opened this thing three separate
times before it did anything besides throw me back at a login screen I
had no account for, and then it just sat there 'downloading' forever.
Somebody should watch this for five minutes before shipping it."
