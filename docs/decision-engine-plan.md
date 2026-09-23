# System 1 Decision Engines (Jev / Laya) — Implementation Plan

**Status:** Proposed
**Date:** 2026-09-21
**Author:** Nurby backend

## 1. Goal

Add a pluggable **decision-engine** seam so an admin can put a System 1 model
(TypeSafe **Jev**, hosted/closed, or ConvAI **Laya**, open/self-hosted) in front
of Nurby's expensive LLM/VLM reasoning path. These models take unstructured
state in and return a **typed decision** (`choice` / `score`) with a
**calibrated confidence** in a single forward pass — no token generation, cannot
hallucinate free text. Admin picks the backend (or `off`) per deployment.

Non-goal: replacing the reasoning models. Decision engines are a cheap,
fast **pre-filter / router / scorer** that gates the existing path.

## 2. Why it fits Nurby

Places we currently pay a full LLM turn for a decision that is really a typed
classification:

| Use case | Current path | Decision engine call |
|---|---|---|
| Alert triage (real event vs noise) | VLM caption then rules | `choice{real, noise}` + conf, before caption |
| Event → rule/persona routing | LLM classify | `choice{rule_ids}` |
| Rule condition eval | brittle if-then / LLM | `choice{true,false}` |
| Escalation prioritization | heuristic KIND_RANK | `score(0..1)` |
| Alert feedback scoring (#195) | LLM judge | `score` usefulness/correctness |

Win: ~2 orders faster + no hallucination → cheap gate in front of reasoning
models. Low-confidence decisions fall through to the existing LLM path, so
behavior is never worse than today.

## 3. Design principles

1. **One contract, two backends.** Jev and Laya share the same I/O shape, so a
   single `Protocol` + factory, mirroring `shared/reasoning.py` and the
   FindAnything `"local"` vs remote microservice split.
2. **Off by default.** New feature ships dark; every call site has a safe
   fallback to the current behavior. Mirrors the reasoning-controls rollout.
3. **Privacy-first default.** Camera state is sensitive. When enabled, default
   to **Laya self-hosted** (nothing leaves the VPC). Jev is opt-in (egress to a
   third-party closed API).
4. **Never fire irreversible actions on a raw decision.** A decision only
   gates/orders; the existing guardrails (e-stop, confirmation) still apply.
5. **Confidence-gated.** Below `min_confidence`, ignore the decision and use the
   LLM path. Log both for offline benchmarking.

## 4. Architecture

### 4.1 The seam — `shared/decision_engine.py`

```python
from typing import Protocol, TypedDict, Literal

DecisionKind = Literal["choice", "score"]

class DecisionSchema(TypedDict, total=False):
    kind: DecisionKind
    choices: list[str]        # for kind="choice"
    # score is implicit 0..1

class Decision(TypedDict):
    choice: str | None
    score: float | None
    confidence: float         # calibrated, 0..1
    engine: str               # "jev" | "laya", for telemetry
    latency_ms: float

class DecisionEngine(Protocol):
    async def decide(self, state: str, schema: DecisionSchema) -> Decision: ...
    async def health(self) -> bool: ...
```

- `JevEngine` — async HTTP client to TypeSafe API. Auth via stored key.
  Handles their "function-call" request/response shape, maps to `Decision`.
- `LayaEngine` — two sub-modes, mirroring FindAnything grounding:
  - `local`: in-process / sidecar inference of a Laya checkpoint.
  - `remote`: HTTP to a self-hosted Laya microservice URL.
  Default checkpoint: 322M multilingual (matches Nurby's i18n need).

Factory:

```python
def build_decision_engine(session) -> DecisionEngine | None:
    prov = get_setting("decision_engine_provider")  # "jev"|"laya"|"off"
    if prov == "off": return None
    ...  # resolve Provider row / url / key, return engine
```

### 4.2 Config storage — reuse existing infra

- **Secrets / URL:** reuse the `Provider` row (`shared/models/accounts.py`) with
  `kind in {"jev","laya"}`. Gives us `api_key`, `base_url`, `active` flag, and
  admin CRUD for free. Token-cap columns stay NULL (N/A). **Note:**
  `Provider.api_key` is currently plaintext `String(512)` — a Jev key needs
  real encryption (`shared/crypto`) added first, and the settings API must be
  write-only for it. Decision kinds carry no VLM/LLM dispatch, so they must be
  filtered out of all provider selectors (see Phase 0).
- **Selection & tuning:** new `app_settings` keys (default = off):

```python
"decision_engine_provider": "off",        # "jev" | "laya" | "off"
"decision_engine_provider_id": None,       # which Provider row to use
"decision_engine_mode": "remote",          # laya: "local" | "remote"
"decision_engine_min_confidence": 0.8,     # below -> fall back to LLM
"decision_engine_shadow": True,            # log-only, don't gate (rollout)
```

### 4.3 Call sites (phased, guarded)

Each site: `engine = build_decision_engine(...)`; if `None` or shadow, keep
current behavior. First real integration = **alert triage** in the ingestion/
perception path (highest volume, clearest win, safe fallback).

## 5. Phases

**Phase 0 — Seam + settings + kind isolation (no behavior change).**
`shared/decision_engine.py` (Protocol, TypedDicts, factory returning `None`),
app_settings keys. **Critical (SEM review):** `jev`/`laya` are NOT AI
providers. Every unfiltered `active + limit(1)` selector must exclude them or
they silently break core paths:
- `services/perception/vlm.py:93` `get_active_provider()` (no kind filter, no
  order_by) → a `laya` row makes `describe()` return `None`, killing VLM
  captioning deployment-wide.
- `services/search/embeddings.py:30`, `services/agent/summarizer.py:435`,
  `services/api/routes/rules_nl.py:365` — same pattern.
- `services/api/routes/doctor.py:394` health-checks every active provider.
- `auth.py:486` / `system.py:487` `has_provider` onboarding gate over-counts.
- `services/escalation.py` `pick_stronger`: unknown kind ranks `UNKNOWN_RANK=5`
  (stronger than ollama=9), so a decision engine can be picked as an agent
  retry target → `LLMProviderUnsupportedError`. Exclude decision kinds from the
  candidate query.
Add a shared `is_decision_kind(kind)` helper and filter at all the above.
No migration needed: `Provider.kind` is `String(32)`, no CheckConstraint/enum.
Unit tests for the factory + every isolation filter. Ships dark.

**Phase 1 — LayaEngine (remote).**
HTTP client to a self-hosted Laya service, `Decision` mapping, health check,
timeout/retry, calibrated-confidence passthrough. Fake for tests. No call site
wired yet.

**Phase 2 — Alert triage in shadow mode.**
Wire the engine at the perception seam. **Correction (SEM review):** noise
culling already happens *before* the VLM caption via the CLIP zero-shot
`services/perception/vlm_gate.py` (`_should_call_vlm` → enqueue in
`pipeline.py` Step 5). The decision engine must justify itself *against/on top
of* that gate, not re-implement it. Insertion point: alongside `vlm_gate` in
`_should_call_vlm`. `decision_engine_shadow=True`: run the engine, log
`Decision` + the CLIP-gate decision + the eventual LLM/VLM label, **do not
gate**. Benchmark must include a calibration reliability curve, not just
precision/recall.

**Phase 3 — Confidence-gated triage (opt-in).**
Flip shadow off per deployment. High-confidence `noise` short-circuits before
the VLM caption; everything else falls through. Metrics: LLM calls saved,
false-negative rate vs shadow baseline.

**Phase 4 — JevEngine.**
Add the hosted backend behind the same Protocol. Admin can select `jev`.
Egress warning surfaced in UI. Same shadow → gated rollout.

**Phase 5 — More call sites.**
Routing, rule-condition eval, feedback scoring (#195). One at a time, each
shadow-first.

**Phase 6 (deferred) — LayaEngine local mode.**
In-process/sidecar inference to drop the network hop, if the remote hop proves
to be the bottleneck.

## 6. Frontend

- Admin settings section (mirror `MqttSection.tsx` pattern): pick provider
  (`off`/`laya`/`jev`), pick/create the Provider row, set min-confidence and
  shadow toggle.
- Jev selection shows an **egress warning** (camera state leaves your network).
- Read-only panel: recent decisions, confidence histogram, LLM-calls-saved.

## 7. Testing

- Unit: factory resolution (off/laya/jev), `Decision` mapping, confidence gate,
  fallback-on-error, fallback-on-low-confidence.
- Fakes for both engines (`SimpleNamespace`-style, like reasoning tests).
- Integration: shadow mode logs both paths and never changes output.
- Benchmark harness: replay recorded alert states through the engine, compare
  vs the LLM label, report precision/recall + latency per backend.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Jev is closed, no papers/open weights (Sept 2026), disputed origin | Default Laya; treat Jev benchmarks as vendor claims; bench on our own data before trusting |
| Camera state egress to third party (Jev) | Laya default, explicit egress warning, opt-in only |
| Calibration drift → bad gating | Confidence gate + shadow baseline + false-negative metric before flipping on |
| Engine down / slow | Health check, timeout, fallback to LLM path (fail-open to current behavior) |
| New Provider kinds break escalation + VLM/LLM/embedding selectors | Phase 0 `is_decision_kind` filter on every unfiltered `active+limit(1)` selector and on `pick_stronger` candidates (SEM review: NOT free, `Provider.kind` has no constraint so any selector picks them up) |
| `Provider.api_key` is plaintext `String(512)`, not encrypted | Add real column encryption (`shared/crypto`) before storing a Jev key; settings API write-only, never echo key back (follow `push_fcm_service_account` precedent) |
| Laya `remote` URL = SSRF vector | Route the HTTP client through `shared/netpolicy`, same as grounding remote |
| Network call on highest-volume ingestion path stalls perception | Per-camera timeout + concurrency cap + fail-open skip, mirror `vlm_backlog_capacity_per_camera` |
| Jev hosted egress cost | Rate limit + count against agent daily budget (`estimate_cost`) |

## 9a. Product / UX (PM review)

**Core product fork — decide this first.** The engineering plan treats the
decision engine as an *invisible cost optimizer* (a silent gate that skips LLM
calls). A user asking "at which state did Laya give what response, and can I
place it in my workflow" wants the *opposite*: a **visible, placeable decision
node**. These are two different products.

- **Model A — Invisible optimizer.** Laya/Jev silently pre-filter. User never
  sees it. Simple, but for a *security* product a silent gate that suppresses a
  real alert as "noise" with no trace is a trust killer. **Not acceptable
  alone.**
- **Model B — Visible decision layer (recommended).** Every decision is
  traceable on the event it affected, and the engine is a first-class step
  users can *place* in rules/workflows. More UI work; correct for trust.

Ship the seam invisibly (Model A internals) but the **product surface is Model
B**. Requirements below assume B.

### Traceability — "at which state, what did Laya say?"
The `Decision` (choice/score, confidence, engine, latency) must be **persisted
per event and shown on the event/alert detail**, not only in an aggregate
panel. On any alert:
- "Laya decided **noise**, confidence 0.91, 28 ms" as a first-class row.
- If the engine gated the event (short-circuited the VLM), say so explicitly:
  "Skipped AI caption because Laya scored this below threshold."
- **Suppressed-events view (BLOCKER for a security product):** a browsable list
  of everything the engine killed as noise, so a user can audit false negatives
  and one-click "this was real → retrain / lower threshold." Without this, a
  gated deployment can silently drop real events and no one ever knows.

### Workflow placement — "send it to Laya for X"
Expose the engine as a **rule/sequence node** (`rule_schema.py`,
`rule_starters.py`), not just a hidden gate:
- Condition node: "when Laya `choice(person,pet,vehicle)` == pet".
- Score gate: "only alert if Laya `score(urgency)` > 0.7".
- Router: "if Laya says delivery → notify persona A; if intruder → escalate".
So a user can wire "detected a cat → ask Laya {indoor/outdoor} → route" without
touching backend config. Admin enables the backend; end user composes with it.

### Two personas, two surfaces
- **Admin (setup):** picks `off`/`laya`/`jev`, provider row, min-confidence,
  shadow toggle, self-host URL / Jev key (write-only), egress warning for Jev.
  Sees health, latency, error rate, calls-saved, **$ egress for Jev**.
- **End user (compose + observe):** does NOT see provider config. Sees Laya as a
  named capability in the rule builder and as decision rows on their events.
  Needs a plain-language explainer: "Laya is a fast local classifier that
  screens events before the AI writes a description."

### Onboarding / mental model
- One-line explainer + a diagram in the admin panel showing where the engine
  sits: `motion → CLIP gate → [Laya/Jev] → VLM caption → rules → alert`.
- Distinguish it from the existing CLIP `vlm_gate` so users don't think it's
  redundant (name them distinctly, e.g. "Motion screen" vs "Decision engine").
- Shadow mode needs a user-facing "trial" framing: "Laya is watching in the
  background. Here's what it *would* have decided this week" before any gating.

### Edge cases the plan does not yet cover
- **Engine ↔ LLM disagreement:** surface it in shadow ("Laya: noise / AI: real")
  — this is the whole benchmark signal, must be visible, not just logged.
- **Low confidence:** show "unsure, fell back to AI" rather than hiding it.
- **Engine down / slow:** user-facing banner + per-event "engine unavailable,
  used AI" note, so a quiet outage isn't invisible.
- **Multilingual:** Laya 322M covers 100+ langs; make the active checkpoint and
  its language coverage visible so an admin in an unsupported locale isn't
  silently mis-served.
- **Threshold changes are retroactive-feeling:** when an admin lowers
  min-confidence, show the projected effect on last week's suppressed set before
  applying.
- **Jev vs Laya switch:** decisions are engine-tagged; don't let a mid-stream
  backend swap silently change alerting behavior without a heads-up.
- **Feedback loop:** the #195 usefulness/correctness signal should feed a
  "Laya was wrong here" path that an admin can act on (threshold or retrain).

### PM verdict
Backend seam: strong. **Product surface: currently too thin** — §6 as written
(a settings panel + one aggregate decisions panel) does not answer "where does
this fit / what did it decide on my event / can I place it in a workflow."
Elevate traceability-per-event, the suppressed-events audit view, and
rule-node placement from "nice-to-have" to **in-scope for the gated release
(Phase 3)**. A silent gate on a security product without an audit trail is a
NO-GO on trust grounds regardless of how good the model is.

## 9. Rollout

Ship dark (Phase 0–1) → shadow on staging (Phase 2) → gated opt-in per
deployment (Phase 3) → Jev backend (Phase 4) → expand (Phase 5). Every step
reversible via the `decision_engine_provider="off"` kill switch.
