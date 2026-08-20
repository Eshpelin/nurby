# Agent reasoning gaps — the "does it actually think?" audit

Status: findings, 2026-08-20. Scope: the two loops that turn frames into
understanding — the idle-time enrichment loop
(`services/perception/vlm_enrichment_worker.py`) and the Ask/agent tool-use loop
(`services/agent/driver.py`).

Prompted by a comparison against terminal coding agents (opencode, crush). The
short answer to "are we doing multi-round thinking": yes, more than most, and
the rounds are not wired to consequences. See §What we already have.

## What we already have

The enrichment worker is a real multi-round loop, not a single VLM call:

- Four lenses per observation, one per idle cycle:
  `attributes -> temporal -> anomaly -> summary`.
- Passes are append-only and immutable (`ObservationVlmPass`). Raw lenses never
  touch the caption; only the `summary` lens does.
- The `summary` lens is a synthesis round over the prior passes' text.
- `VERIFY_PROMPT` is a self-critique round: it asks whether every concrete
  detail in the summary is supported by at least one source pass.

Chain-of-passes plus a verifier is further than either coding agent we compared
against goes. The gaps below are about what the rounds are allowed to change.

## G1. The verifier is decorative

`_run_summary` (`vlm_enrichment_worker.py:336`) computes `verdict`, writes it to
`attrs["verify"]`, and then calls `_write_summary` **unconditionally**. A summary
the model just flagged as `unsupported` still becomes
`Observation.vlm_description` and still gets embedded into search.

So the system detects its own hallucination and then indexes it.

Fix: on `unsupported`, retry the summary once with the unsupported detail named
in the prompt. If the retry is also unsupported, fall back to the highest-signal
raw pass text rather than the synthesis, and record the downgrade. Never embed a
summary that failed its own check.

Size: half a day. Highest value per hour in the whole system. Issue #127.

## G2. The anomaly lens has no history

`LENS_PROMPTS["anomaly"]` asks "is anything unusual here" against **one still**,
with no priors. The model cannot know unusual, because it has never been shown
usual. Nothing in `services/perception/` or `services/agent/` computes a
per-camera baseline today.

Fix: a cheap deterministic baseline keyed by (camera, hour-of-day, weekday) —
label counts, count of distinct known faces, the plate set, typical dwell. Feed
five lines of it to the anomaly lens as `extra_context`:

> This camera in this hour normally sees 2-4 person, 1 car, faces {Mom, Dad}.
> This frame: 1 person, 0 car, one unrecognized face.

The lens then does grounded comparison instead of vibes. The same table unlocks
`docs/industrial-automation-plan.md` §4L (rule proposals from observed patterns)
and part of §4I (metric primitives).

Size: 2-3 days. Biggest single quality lever available. Issue #129.

## G3. Temporal context is three frames wide

`_temporal_montage` builds `[prev, current, next]` from one recording — seconds
of memory. The observation's own `incident_id` and the journey tracker are never
consulted, though both already exist.

Fix: pass the incident/journey the observation belongs to as lens context, so
the temporal lens sees "this is minute 4 of an incident that started with a van
stopping at the curb" rather than three near-identical stills.

Size: 1-2 days. Data already exists; this is plumbing. Issue #130.

## G4. Widen-then-fail is prompt-only, and citations are unchecked

Two separate defects in `driver.py`, same root cause: rules that live in the
system prompt where a small local model can silently skip them.

1. The escalation ladder (24h -> 168h -> 720h -> `get_last_sightings`) is prose
   in `SYSTEM_PROMPT_TEMPLATE`. Nothing enforces it, so a weak model answers
   "not seen" off one empty 24h window.
2. Every load-bearing claim is supposed to carry `[obs:<uuid>]`. No code checks
   that a cited id ever appeared in a tool result.

Fix: make both deterministic. `query_observations` auto-retries a widened window
on zero rows and returns `widened_to: 168` so the answer must acknowledge it. A
final pass verifies every `[obs:...]` / `[journey:...]` / `[vlm:...]` in the
answer against the run's tool results, and strips or flags the ones that were
never returned.

Size: 1 day for both. Issue #128.

## G5. No persistent household context (borrowed from crush)

crush generates an `AGENTS.md` per project by analyzing the codebase, and feeds
it as a system-prompt extension on every run, so the agent starts warm instead of
rediscovering conventions each session.

Nurby's equivalent does not exist. `get_household_snapshot` is a turn-0 tool
call: it costs a round-trip, and only returns live state, not accumulated
knowledge. There is no stored "what this household is like" — which camera looks
at what, which zones are named, who is normally home when, which plates are the
household's own.

Fix: a periodically regenerated household context document, persisted and
injected into the system prompt. It subsumes the turn-0 snapshot call for most
questions and shares its source data with the G2 baseline table.

Size: 2-3 days, and it should be built after G2 so the two share one table. Issue #131.

## G6. No mid-run model escalation (borrowed from crush)

crush switches models mid-session while preserving context. Nurby picks one
provider per `AgentRun` and per VLM pass, and is stuck with it: when a cheap
local model returns `cannot_tell`, fails its verify round, or burns turns without
converging, there is no path to retry that one step on a stronger model.

Fix: an escalation policy at the two points where quality is already measured —
the enrichment verify round (G1) and the agent's forced-synthesis path. Retry the
failed step once on the household's strongest configured provider, record which
model produced the kept answer.

Size: 1-2 days, depends on G1. Issue #132.

## What the coding agents did NOT have worth taking

Both opencode and crush are terminal coding TUIs. Their headline mechanisms are
either already present here or do not apply:

- **Auto-compaction near the context limit** (both). Not our bottleneck: the
  driver caps at 12 turns and truncates each tool result to 8000 chars, so chat
  history never approaches the window. Our token pressure is tool-result width,
  not conversation length.
- **Sub-agent / task-delegation tool** (opencode). Ask answers one question
  against an indexed store; there is no sub-task to fan out to yet. Revisit if
  multi-camera investigations get long.
- **Permission gating on tool execution** (both). The agent is read-only by
  design and cannot create or edit rules, so there is nothing to gate.
- **LSP as external ground truth** (both). The concept transfers — YOLO
  detections and journeys are our "diagnostics" — and G2/G3 are that idea applied.
- **Workspace sharing across clients** (crush). Interesting for a shared
  household Ask session. Not a quality problem.

## Order

G1 -> G4 -> G2 -> G3 -> G5 -> G6. G1 and G4 are self-contained and land in a
session each. G2 is the one that changes what the system can notice.
