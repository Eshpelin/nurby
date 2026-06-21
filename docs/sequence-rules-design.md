# Sequence Rules — temporal, multi-step automations (design sketch)

Status: **Draft sketch** (pre-implementation, refinement round 1). Owner: TBD. Last updated: 2026-06-21.

**Decisions folded in (round 1):**
- **Absence detection is core to v1** — a sequence can fire when an expected step
  does NOT happen in time ("package not picked up in 10 min"). Two action sets:
  `on_complete` and `on_timeout`.
- **All correlation modes are supported** (person / journey / incident / camera /
  none), chosen per rule, not a single fixed mode. See §4.
- **Cross-camera in v1** — steps may span cameras (correlated by person/journey).
- **Steps can be any trigger predicate OR a FindAnything/verify check.**

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
  correlate_by: person | journey | incident | camera | none   # how steps bind (§4)
  cameras: [ ... ]                          # optional extra scope; omit ⇒ cross-camera
  on_refire: ignore | restart              # step 0 fires again while active (§6)
  max_active: 20                            # cost guard: concurrent instances (§6)
  steps:
    - check: <any trigger predicate OR locate/verify>   # e.g. locate("a key in his hand")
      pre_gate: { motion: true }            # cheap filter before any GPU work
      within_seconds: 30                    # deadline from the previous step
    - check: locate("a key in the key box")
      within_seconds: 120
on_complete: [ notify, ... ]               # all steps satisfied; sees {{trigger.*}}, {{steps.N.*}}
on_timeout:  [ notify "Sam didn't put the key away", ... ]   # a step timed out (absence); optional
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

## 4. Correlation (all modes, chosen per rule)

Correlation decides whether a new observation belongs to an in-flight instance.
The step **window always bounds**; the correlation key **narrows**. All modes are
supported; the user picks per rule (the right one depends on the automation):

- **`person`** — same recognized identity (`person_id` from face/re-id).
  Camera-independent, so it works **cross-camera**. Most precise when the face is
  seen; degrades when it isn't. Best for "a specific person does A then B."
- **`journey`** — Nurby's cross-camera person track (a journey stitches a
  person's path across cameras + brief identity gaps). The **strongest
  cross-camera binding**; as good as journey quality. Best for "enters front →
  kitchen."
- **`incident`** — the sighting cluster the start observation belongs to. Strong
  same-area binding; cross-camera only insofar as incidents span cameras.
- **`camera`** — same camera, no subject binding. For single-camera,
  subject-agnostic sequences (a door, a package on one cam, a parking spot).
- **`none` (window-only)** — any observation within the window, anywhere.
  Loosest; for global "X then Y" with no subject. False-positive-prone — pair
  with short windows + specific step checks.

Optional **`cameras`** scope narrows any mode to specific cameras/zones (omit for
cross-camera). The engine computes the correlation key from the observation per
the chosen mode; an instance only advances on observations with a matching key.

**Honesty:** cross-camera `person`/`journey` binding is the least reliable link
(re-id across cameras drops), and small-object grounding compounds it — so the
most ambitious sequences (the key-box example) are the most approximate.

## 5. UX

Rule builder gains a **"Then…"** step adder under the trigger. Each step picks a
*check* (reusing the existing trigger + FindAnything/verify pickers) and a
"within N seconds" window; a **correlation** selector; per-step + overall
timeouts; and the on-timeout behavior. A new "Sequence" summary line in plain
language ("When Sam is seen, then within 30s a key in hand, then within 2m a key
in the box → notify").

## 6. Instance lifecycle, vars, cost & safety

**Lifecycle (per instance):**
- **start** — step 0 (trigger) matches; compute the correlation key; create
  `active` instance at `step_index = 1`, `deadline = now + step1.within_seconds`.
- **advance** — an observation with a matching key satisfies the current step
  within its deadline → bump `step_index`, arm the next deadline. Last step →
  `completed` → run **`on_complete`** actions.
- **timeout** — the sweeper finds `now > deadline` → `expired`; if `on_timeout`
  actions exist, run them (this is absence detection).
- **re-fire** — step 0 fires again while an instance is `active`. Policy
  `on_refire`: **`ignore`** (default — don't reset progress) or **`restart`**
  (fresh instance/deadline). One `active` instance per `(rule, key)`.

**Two action sets** (both see the vars below):
- **`on_complete`** — the success chain (the existing action chain, reused).
- **`on_timeout`** — the absence chain ("the expected thing didn't happen"),
  with which step timed out available. Separate so success vs absence can do
  different things.

**Vars threading:** templates/conditions in either chain can reference
`{{trigger.*}}` (the start observation) and `{{steps.0.*}} … {{steps.N.*}}` (each
satisfied step's data — detected label, locate boxes/`found`, observation id,
camera, timestamp).

**Cost & safety:**
- **`max_active` cap** per rule + a global cap; at the cap, new starts are
  dropped (logged), not queued — bounds GPU + state.
- **Cheap `pre_gate` before any locate step**, plus the existing grounding global
  gate + result cache, so an in-flight sequence never grounds every frame.
- Keep the FindAnything **corroboration/verify** gate on the payoff action —
  sequences *compound* false positives.
- `on_timeout: fire` is the more autonomous path (fires with no positive
  detection); opt-in, and for security-grade alerts, verifiable.

## 7. Phasing

v1 now includes everything decided in round 1 (absence firing, all correlation
modes, cross-camera, any-check steps), so it's a larger build — roughly
FindAnything-sized. Internal build order (each lands working + verified before
the next):

1. **Engine core** — `rule_sequence_instances` table + migration; the
   start/advance state machine; the sweeper loop; `camera` + `incident`
   correlation; linear steps with cheap-predicate checks; `on_complete` actions.
2. **Absence + control** — `on_timeout` action chain + sweeper firing;
   `on_refire` policy; `max_active` caps; `{{trigger.*}}`/`{{steps.*}}` vars.
3. **FindAnything steps** — locate/verify as step checks, behind the `pre_gate`
   + grounding gate/cache.
4. **Cross-camera identity** — `person` + `journey` correlation.
5. **Builder UI** — the "Then…" step editor, correlation + window controls, the
   `on_complete`/`on_timeout` action sets, and the plain-language summary.

- **Defer (v2+):** branching DAGs / any-of / parallel steps; a timeline overlay
  of in-flight sequences; action-recognition gestures ("putting" vs the
  before/after states).

## 8. Honest limits

- Correlation in v1 is **approximate** (incident/camera, not guaranteed-same-subject).
- Single-frame grounding judges **states** ("a key is in the box"), not **actions**
  ("he put it in"); sequencing the states (no key → key, within the window)
  *approximates* the action but isn't true action recognition.
- This is real engineering, not a toggle: DB table + migration, an engine state
  machine, a sweeper loop, schema + validation, and builder UI. Multi-part.
