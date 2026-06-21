# Sequence Rules — temporal, multi-step automations (design sketch)

Status: **Draft sketch** (pre-implementation). Owner: TBD. Last updated: 2026-06-21.

## 1. The problem

Today a rule is **one trigger + a synchronous action chain evaluated on a single
frame** (the triggering observation). It can check many things *about that one
moment* (chain several FindAnything/verify actions, gate with `{{vars.*}}`), but
it cannot express anything that unfolds **over time**:

- "Sam comes in → within 2 min a key appears in the key box → else nudge him."
- "A package is dropped → not picked up within 10 min → alert."
- "A car enters the driveway → no one approaches the door within 60s → alert."
- "Front gate opens → garage door opens within 30s" (expected pairing).

These are **temporal sequences** across multiple observations/frames. The engine
fires once and runs the chain on one frame; it has no "wait, then check for B."

## 2. Model

Extend a rule with an optional **`sequence`** block. The existing trigger becomes
**step 0 (the start)**; then ordered steps, each a *check* + a *time window*. The
action chain runs when all steps complete (or via a timeout branch).

```yaml
trigger: face_recognized(Sam)              # step 0 — starts an instance
sequence:
  correlate_by: incident | person | camera # bind the steps to the same subject/scope
  steps:
    - check: locate("a key in his hand")    # a trigger-predicate OR a locate/verify check
      pre_gate: { motion: true }            # cheap filter before any GPU work
      within_seconds: 30                    # deadline from the previous step
    - check: locate("a key in the key box")
      within_seconds: 120
  on_timeout: drop | fire                   # "didn't happen" can itself be an alert
actions: [ notify, ... ]                    # run on completion; sees {{steps.N.*}}
```

Incremental by design: the existing trigger + action chain are unchanged; a rule
with no `sequence` behaves exactly as today.

## 3. Engine architecture

Two additions to `services/events/`:

1. **Instance store** — a DB table `rule_sequence_instances`
   (`id, rule_id, correlation_key, step_index, started_at, step_deadline,
   vars JSON, status`). Auditable, survives restart, and the timeline can show
   in-flight/completed/expired sequences. (Redis-with-TTL is tempting but TTL
   expiry fires no code, so we'd still need a sweeper — DB + sweeper is cleaner.)

2. **Engine + sweeper:**
   - On each observation the engine, besides normal rule matching:
     - **starts** an instance when a sequence rule's step 0 (trigger) matches,
       scoped by the correlation key (dedup: one live instance per
       `(rule, key)`);
     - **advances** any in-flight instance whose *current* step check matches,
       within its deadline and correlation. Last step → run the rule's action
       chain (with `{{steps.N.*}}` available); else arm the next step's deadline.
   - A **sweeper loop** (mirrors `reid_sweeper` / `face_merger`) expires
     instances past `step_deadline`. `on_timeout: fire` runs a timeout branch —
     this is how "expected thing did NOT happen" becomes an alert.
   - **Expensive (locate) step checks run only while an instance is actively
     waiting on that step**, the observation passes the step's cheap `pre_gate`,
     and we're inside the window. That bounds GPU to live sequences. Reuse the
     grounding global gate + result cache.

## 4. Correlation (the hard part)

Binding steps to the *same* subject is what makes "Sam's key" not match "anyone's
key." Three levels, increasing accuracy + cost:

- **`camera` (+ window)** — same camera within the window. Simplest, approximate
  (could match a different subject). Fine default for many rules.
- **`incident`** — bind to the incident/cluster the start observation belongs to.
  Nurby already groups repeat sightings into incidents, so this is a strong
  middle ground and the **recommended v1 default**.
- **`person`** — bind to the recognized identity (face/re-id) across steps. The
  true "Sam" binding, but only as reliable as re-id holding frame-to-frame.

## 5. UX

Rule builder gains a **"Then…"** step adder under the trigger. Each step picks a
*check* (reusing the existing trigger + FindAnything/verify pickers) and a
"within N seconds" window; a **correlation** selector; per-step + overall
timeouts; and the on-timeout behavior. A new "Sequence" summary line in plain
language ("When Sam is seen, then within 30s a key in hand, then within 2m a key
in the box → notify").

## 6. Cost & safety

- **Bound concurrent in-flight instances** (per rule + global) to cap GPU + state.
- **Cheap pre-gate before any locate step**; reuse the grounding gate + cache.
- Keep the FindAnything **§6 corroboration / verification** principle on the
  final action — sequences *compound* false positives, so the payoff action
  should still be gated.
- `on_timeout: fire` is powerful but is the more autonomous path; keep it opt-in
  and, for security-grade alerts, verifiable.

## 7. Phasing

- **v1 (MVP):** linear steps; `correlate_by: incident` (+ camera fallback); each
  step is a trigger-predicate OR a locate/verify check; per-step window;
  `on_timeout: drop`; one instance per `(rule, key)`; DB table + sweeper; builder
  "Then…" UI. Covers "Sam enters → key in the box within 2m."
- **v2:** `person` correlation; `on_timeout: fire` ("didn't happen") branch;
  any-of / parallel steps; richer `{{steps.*}}` threading; timeline overlay of
  in-flight sequences.
- **Defer:** branching DAGs, cross-camera journeys as the correlation key,
  action-recognition gestures ("putting" vs the before/after states).

## 8. Honest limits

- Correlation in v1 is **approximate** (incident/camera, not guaranteed-same-subject).
- Single-frame grounding judges **states** ("a key is in the box"), not **actions**
  ("he put it in"); sequencing the states (no key → key, within the window)
  *approximates* the action but isn't true action recognition.
- This is real engineering, not a toggle: DB table + migration, an engine state
  machine, a sweeper loop, schema + validation, and builder UI. Multi-part.
