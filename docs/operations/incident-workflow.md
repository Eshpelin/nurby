# Incident resolution + ownership workflow

**Issue:** #197 · **Status:** shipped. Reuses existing incident grouping, evidence bundle (#225), and camera scope (#201).

## Why

Grouping, acknowledgment, notes and clips existed, but "seen" and "resolved"
are different outcomes, and a shared household/team could not tell who handled
an incident. This connects evidence, ownership and resolution so an incident
can be inspected and closed without hunting across pages.

## Model (#197 columns on `incidents`)

- `status` — `open` (default) / `resolved` / `dismissed`, indexed for triage.
- `resolution_reason` — free text.
- `resolved_at`, `resolved_by_user_id` — who handled it and when.
- `assigned_to_user_id` — optional owner for business pilots; households ignore it.

Migration: `alembic/versions/d2e3f4a5b6c7_incident_resolution_workflow.py`.

## Endpoints (all permission-scoped on the incident's camera)

- `GET  /api/incidents` — now takes `?status=open|resolved|dismissed`.
- `GET  /api/incidents/{id}` — consolidated detail: summary, observations,
  trigger signature, `ownership` (status + who resolved/assigned, by display
  name, + when), and an `evidence_export` block (the params for the scoped
  `/api/recordings/evidence-bundle` endpoint, so export is one click).
- `POST /api/incidents/{id}/resolve` `{reason?}` — records resolver + time.
- `POST /api/incidents/{id}/dismiss` `{reason?}`.
- `POST /api/incidents/{id}/reopen` — clears the resolution.
- `POST /api/incidents/{id}/assign` `{user_id|null}` — assign / unassign;
  validates the assignee exists.

Every route funnels through `_get_incident_in_scope`, so a user cannot
inspect, resolve, or export an incident on a camera they cannot see.

## Acceptance

- Inspect + resolve without hunting: the detail view carries summary,
  evidence, trigger, ownership, and the export link; resolve/dismiss are one
  POST. ✅
- Shared users see who handled it and when: `ownership.resolved_by` +
  `resolved_at` (display name, not a raw id). ✅
- Exports and related evidence obey camera permissions and retention: the
  export reuses the already-scoped evidence bundle (#225/#201), which
  re-checks the caller's ACL itself. ✅

Source: `services/api/routes/incidents.py`, `shared/models/observations.py`
(Incident), tests `tests/test_incident_workflow.py`.
