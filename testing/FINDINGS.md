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

(none yet)

## Working well

Positive confirmations, so "what works" is data too. One line each:
persona, flow, date.

(none yet)
