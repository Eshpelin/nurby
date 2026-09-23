# Reversible alert tuning from reviewed history

**Issue:** #196 · **Depends on:** #195 (structured feedback) · **Status:** engine + endpoints shipped.

## Idea

Once users mark alerts `useful` / `correct_but_not_useful` / `incorrect`
(#195), Nurby can propose concrete changes that cut nuisance alerts. The hard
rule: **no automatic silent changes**. Every change is proposed, previewed on
history, accepted explicitly, and reversible.

## What it proposes

`services/events/tuning.py` `analyze(rule, events)` looks at a rule's reviewed
alerts and proposes (each with sample size + the example events behind it):

| Trigger in feedback | Suggestion | Field |
| --- | --- | --- |
| ≥3 `duplicate` | raise the cooldown | `cooldown_seconds` |
| ≥3 `wrong_object` | raise the confidence gate | `conditions.min_confidence` |
| ≥3 `timing`, clustered in hours | mute that window | `conditions.time_window` |
| `correct_but_not_useful` ≥ useful | demote to a quiet detection | `severity` |

Nothing fires below `MIN_SAMPLE` (3), so a single gripe never moves config.

## Preview (replay)

`preview(suggestion, events)` replays a proposed change over the rule's past
events and returns `would_suppress` / `would_keep`, plus `nuisance_removed`
(good) and `useful_lost` (the recall cost, never hidden). It carries an
explicit caveat: replay shows nuisance reduction on past events but cannot
establish future recall.

## Endpoints

- `GET  /api/rules/{id}/tuning-suggestions` - proposals with samples + examples.
- `POST /api/rules/{id}/tuning-suggestions/preview` - replay one suggestion.
- `POST /api/rules/{id}/apply-tuning` - apply an accepted change; returns
  `previous_value`. **Undo** is a second call with that value. Only a fixed
  allowlist of fields is tunable; anything else is refused.

## Acceptance

- No automatic silent threshold changes: only `apply-tuning` mutates, and only
  when called explicitly.
- Every suggestion shows sample size and the reviewed examples (positive +
  negative event ids).
- Missed-event evaluation: `useful_lost` in the preview surfaces the recall
  cost; pair with the golden set (#214) for labelled-scenario recall testing.

Source: `services/events/tuning.py`, `services/api/routes/tuning.py`,
`tests/test_tuning.py`.
