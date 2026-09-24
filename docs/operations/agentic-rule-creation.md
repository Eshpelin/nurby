# Agentic rule creation (Ask builds rules behind a confirm gate)

**Issue:** #284 · **Status:** shipped (rule create). Rule *edits* and other write tools are follow-ups.

## Why

The Ask agent was advisory-only: 20 read tools + `speak_on_camera`, plus a
`suggest_rule` that just deep-linked to the builder. A user who said "alert me
when a stranger is at the door after 10pm" had to re-enter it. We already owned
the translator (`rules_nl.translate_rule`); this lets the agent draft a real
rule and create it **after an explicit confirm** — safe by construction, and
aligned with the "no silent changes" posture (#196).

## How it works (the confirm gate)

1. The user asks for an automation. The agent calls the new **`draft_rule`**
   tool with a plain-English description.
2. `draft_rule` runs `rules_nl.translate_rule` (the same NL→RuleCreate path the
   `/api/rules/generate` route uses), scopes the draft to the caller's cameras,
   and returns a **`client_action`** proposal — it writes nothing.
3. The driver forwards any tool `client_action` as a typed WS event.
4. The Ask UI renders a **Confirm card** (rule title, summary, warnings) with
   *Confirm & create* / *Cancel*.
5. **Confirm** POSTs the drafted body to the normal `POST /api/rules` create
   path (which applies review-first disabling for consequential rules, #192).
   The agent never writes; the human's click does.

The `client_action` mechanism is generic — future write tools (e.g. Memory
#286) reuse the same propose→confirm gate.

## Backend

- `services/api/routes/rules_nl.py`: factored `translate_rule(db, prompt, …)` out
  of the `/generate` route so the route and the tool share one translator.
- `services/agent/tools/setup_tools.py`: `draft_rule(ctx, description)` →
  `{ok, rule, summary, notes, warnings, client_action, message_for_user}`.
  Refuses a draft that references a camera the caller cannot see
  (`allowed_camera_ids`). Graceful `{ok: false, …}` when no provider / not
  translatable. Registered in the tool registry (preferred over `suggest_rule`).
- `services/agent/driver.py`: emits a `client_action` WS event when a tool
  result carries one; system prompt now allows rule drafting (and forbids
  claiming a rule was created before confirm).

## UI

- `frontend/src/lib/agentWs.ts`: new `client_action` agent-event type.
- `frontend/src/components/ask/AgentResponseCard.tsx`: collects `client_action`
  events into the view model and renders `RuleDraftConfirm` — a confirm card
  that POSTs the drafted rule on confirm, shows warnings, and links to Rules on
  success.

## Acceptance

- [x] The agent turns a plain-language request into a created, enabled rule
  **only after** an explicit confirm; nothing is written otherwise.
- [x] The proposal preview shows what will be created (title, summary, warnings);
  the applied result is the previewed body.
- [x] A user cannot draft a rule touching a camera outside their permission.
- [x] Cancelling writes nothing.
- [ ] (follow-up) Editing an existing rule by description with a diff preview.
- [ ] (follow-up) Attributable audit entry on the created rule (source=agent).

## Deferred

- Rule **edit** proposals (`propose_rule_edit`/`apply_rule_edit`).
- An explicit audit trail marking agent-originated creates.
- Scenes/scripts/helpers and NL dashboards (out of scope).

Source: `services/api/routes/rules_nl.py`, `services/agent/tools/setup_tools.py`,
`services/agent/driver.py`, `frontend/src/lib/agentWs.ts`,
`frontend/src/components/ask/AgentResponseCard.tsx`, tests
`tests/test_draft_rule_tool.py`.
