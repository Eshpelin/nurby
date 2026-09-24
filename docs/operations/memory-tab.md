# Memory tab: read, add, edit and prune what Nurby remembers

**Issue:** #286 · **Status:** shipped. Builds on the confirm gate from #284.

## Why

The `HouseholdFact` store already fed learned/《told》facts into the agent's
context, but there was no way to *see*, *correct*, or *prune* what Nurby knew,
and no first-class "remember this". This surfaces the store and lets a person
tell the agent facts that persist.

## Model reuse (no migration)

`HouseholdFact` already has everything: `text`, `source` (`user` | `agent`),
`status` (`established` | `candidate` | `archived` | `rejected`), `pinned`,
`evidence_count`, timestamps. Two existing invariants do the heavy lifting:

- The curator only auto-modifies `source="agent"` rows, so a fact a person
  writes (`source="user"`) is never rewritten — "user edits are sticky" is
  already true.
- `household_context` feeds only `status="established"` facts into answers, so
  **disabling = archiving** (stops influencing, stays visible), no new column.

## API (`/api/household/facts`, household-wide, authenticated)

- `GET /` — every non-rejected fact, newest first (`include_archived` toggles
  disabled ones). Each carries `source`, `enabled`, `pinned`, and an
  `updated_at`.
- `POST /` `{text, kind?}` — add a user fact (`source="user"`,
  `status="established"` so it feeds answers immediately).
- `PATCH /{id}` `{text?, enabled?, pinned?}` — edit text (durable; curator
  won't touch it), enable/disable (established↔archived), or pin.
- `DELETE /{id}` — prune for good.

## Agent write path (confirm gate)

New **`remember`** tool: when the user says "remember that…", it returns a
`client_action` (`kind: "remember_fact"`) — it saves nothing. The driver's
generic `client_action` event (from #284) drives the Ask **Confirm card**
(`AgentResponseCard` now handles both `create_rule` and `remember_fact`); on
Confirm the client POSTs to `/api/household/facts`. Reads already work: the
agent's context includes established facts, so "what do you remember about the
garage?" is answerable.

## UI

- New **Memory** tab at `/memory` (linked under Ask in the mega-nav): add a
  fact, list with "told by you" / "learned" badges + `updated`, inline edit,
  enable/disable, delete (confirm).
- Ask chat: a "remember this" request shows a Confirm card that saves to
  memory and links back to the tab.

## Acceptance

- [x] View every fact with source + last-updated; add, edit, disable, delete.
- [x] "remember X" stores a fact after confirm; it appears in the tab and
  persists.
- [x] User edit/disable/delete is durable and not overwritten by the curator
  (only `source="agent"` rows are auto-managed).
- [x] Disabled facts stop influencing answers (only `established` feeds
  context) but stay visible.
- [x] Ask answers "what do you remember…" from the same store (via context).
- [ ] (follow-up) Per-guardian privacy scoping of individual facts (the store
  is household-wide today).

## Deferred

- Automatic fact extraction from conversation at scale (kept to explicit
  "remember" + the existing curator).
- Per-guardian scoped/private facts.

Source: `services/api/routes/household.py` (facts API),
`services/agent/tools/setup_tools.py` (`remember`),
`services/agent/tools/registry.py`, `frontend/src/app/memory/page.tsx`,
`frontend/src/components/ask/AgentResponseCard.tsx`, tests
`tests/test_memory_facts.py`.
