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

(none yet)

## Deferred features

Findings that need multi-day feature work, with the reason. Runs pick
these up before starting new persona flows once the open backlog is empty.

(none yet)

## Fixed

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
