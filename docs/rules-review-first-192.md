# Review-first consequential rules (#192)

From the 16 September 2026 product review. The guest-fee template could POST
to a CRM off a tripwire plus a person detection, which does not prove a
distinct unauthorized entrant or a successful charge. This change makes rules
that take a real-world action review-first and keeps their records honest
about what actually happened.

## What "consequential" means

A consequential action reaches outside Nurby and does something a person
would want to review before it fires on its own:

- `device` — drives a registered physical device or relay
- `speak` — speaks over a camera speaker
- `api_call`, `webhook` — writes into another system over HTTP

Informational actions (`notify`, `telegram`, `email`), the in-app `broadcast`,
and internal analysis steps (`verify`, `locate`, `vlm_call`) are not
consequential: at worst they send a message or spend a model call, and there
is no external side effect whose success a rule could fabricate.

The canonical list lives in `shared/consequential.py` (backend) and is
mirrored in `frontend/src/lib/rule-templates.ts`. Keep the two in sync with
the executors in `services/events/actions.py`.

## Shipped

- **Review-first default.** `POST /api/rules` and `POST /api/rules/starters`
  force `enabled = false` when a rule contains a consequential action, in its
  action chain or in a sequence `on_timeout` block. The create response
  carries `review_first: true` so the UI can explain the demotion. A human
  enables the rule from the rule list after reviewing it.
- **Templates land paused.** Consequential templates build with
  `enabled: false`; the gallery card shows a "Starts paused for review" badge.
  The tailgate guest-fee recipe is a review alert only. it notifies and says
  "No fee was charged by this rule," and never calls a billing API.
- **Truthful outcomes.** Action execution records the real result on
  `Event.action_status` (`success` / `failed` / `skipped`) with
  `Event.action_error`. `device`, `webhook` and `api_call` only record
  `success` on a confirmed 2xx/ok delivery. a bad host, timeout, refused
  target, disabled/missing device, or HTTP >= 400 records `failed`. No path
  writes `success` before delivery is confirmed, so a message can never imply
  a downstream action succeeded when it did not.
- **Tests.** `tests/test_review_first.py` covers detection and the create-time
  demotion (including the `on_timeout` case and the starter path).
  `frontend/src/lib/__tests__/rule-template-trust.test.ts` covers the
  template `enabled` defaults and the guest-fee wording.

## Deferred (tracked, not yet built)

- **Shadow mode.** A rule that evaluates and records what it *would* have done
  without firing the consequential action, so an operator can validate a
  recipe against live footage before arming it.
- **Explicit per-fire approval.** An `awaiting_approval` action outcome and an
  approve/deny step before a billing or access-control action runs, distinct
  from the rule-level enabled toggle shipped here.
- **Receipts and duplicate prevention.** Store the downstream system's
  response id/receipt on the event, and suppress duplicate consequential
  actions for the same underlying incident (e.g. one charge per entry).
- **Integration prerequisites.** Per-template documentation of the endpoint,
  auth and payload contract each consequential recipe expects before it can
  succeed.
