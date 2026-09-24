# Incident resolution + ownership workflow

**Issue:** #197 · **Status:** shipped. Reuses existing incident grouping, evidence bundle (#225), and camera scope (#201).

## Why

Grouping, acknowledgment, notes and clips existed, but "seen" and "resolved"
are different outcomes, and a shared household/team could not tell who handled
an incident. This connects evidence, ownership and resolution so an incident
can be inspected and closed without hunting across pages.

## Model

- `incidents`: `status` (`open`/`resolved`/`dismissed`, indexed),
  `resolution_reason`, `resolved_at`, `resolved_by_user_id`,
  `assigned_to_user_id` (migration `d2e3f4a5b6c7`).
- `incident_events` — append-only audit log (`action`, `actor_user_id`,
  `reason`, `detail`, `created_at`) so "who handled it and when" survives a
  reopen, unlike the single `resolved_by` pointer (migration `a3c5e7f9b1d2`).

## Endpoints (all permission-scoped on the incident's camera)

- `GET  /api/incidents` — `?status=open|resolved|dismissed` filter.
- `GET  /api/incidents/{id}` — the **consolidated detail** the UI renders in
  one place:
  - `observations`, `summary_text`, trigger signature.
  - `ownership`: current resolver/assignee (by display name) **plus `history`**,
    the full transition timeline from the audit log.
  - `alerts`: for each alert this incident fired (Events on its observations) —
    `trigger_reason` (the rule), `action_type`/`action_status`/`action_error`
    (delivered / failed / pending), `seen` (ack state), and inline notes.
  - `related_sightings`: sibling incidents on the same cross-camera journey,
    permission-scoped.
  - `exact_clip`: the recording covering the incident's peak moment.
  - `evidence_export`: params for the scoped `/api/recordings/evidence-bundle`.
- `POST /api/incidents/{id}/resolve` `{reason?}` — records resolver + time + log.
- `POST /api/incidents/{id}/dismiss` `{reason?}`.
- `POST /api/incidents/{id}/reopen` — clears resolution, logs the reopen.
- `POST /api/incidents/{id}/assign` `{user_id|null}` — assign / unassign;
  validates the assignee; logged with the assignee name.

Every route funnels through `_get_incident_in_scope`, so a user cannot
inspect, resolve, or export an incident on a camera they cannot see.

## Frontend (one workflow)

`frontend/src/components/IncidentCard.tsx` expands into the workflow: a status
chip, resolve/dismiss (with an optional reason) / reopen, assign-to-me /
unassign, the ownership timeline, the alerts' trigger + action result + seen
state, related sightings, "open exact clip", and the scoped evidence-export
download — so an incident is inspected and closed in place.

## Acceptance

- **Inspect + resolve without hunting** — the detail view + the expanded card
  carry summary, observations, alerts (trigger + action result), related
  sightings, the exact clip, ownership, and export in one place; resolve /
  dismiss / reopen / assign are one action each. ✅
- **Shared users see who handled it and when** — `ownership.history` is an
  append-only audit trail (actor + reason + time per transition), durable
  across reopen. ✅
- **Exports + related evidence obey camera permissions and retention** — every
  read is `_get_incident_in_scope` + `apply_camera_filter` scoped, and the
  export reuses the already-scoped evidence bundle (#225/#201). ✅

Source: `services/api/routes/incidents.py`, `shared/models/observations.py`
(`Incident`, `IncidentEvent`), `frontend/src/components/IncidentCard.tsx`,
tests `tests/test_incident_workflow.py`.

## Deferred

- Resolve-offers-to-ack the still-unseen linked alerts (kept distinct for now:
  the detail shows `seen` state but resolving does not auto-ack).
- A full assignee picker (the API accepts any `user_id`; the UI currently does
  assign-to-me / unassign).
