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

## Working well

Positive confirmations, so "what works" is data too. One line each:
persona, flow, date.

(none yet)
