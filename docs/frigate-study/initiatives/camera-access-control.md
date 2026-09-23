# Initiative: Per-user camera access control

**Source PRs:** #23256 (filter outbound WS broadcasts by camera access), #23294 (filter motion
review by allowed cameras); related #23164 (cross-camera safety for indexed media). **Status:**
VULNERABLE / MISSING on Nurby's main app surface. **Priority:** P1. **Effort:** L.

## The gap (verified)

Nurby has two surfaces with opposite postures:
- **Guardian** — correctly scoped: `_allowed_cameras()` (`services/api/routes/guardian.py`),
  facility + entitlement checks, blur enforcement.
- **Main app** — unscoped: any authenticated user sees everything.
  - **WS broadcasts** (`services/api/ws.py` `_deliver_local`/`broadcast`/`relay_loop`) push every
    camera's events/detections to every connected client; Guardian alerts too.
  - **List endpoints** (`events.py`, `recordings.py`, `observations.py`, `cameras.py`) return all
    rows with no camera filter.

For the single-owner V1 this is acceptable (the only user *is* the admin). It becomes a real
data-leak the moment a second, restricted account exists — which is exactly what V2
(prosumer families) and any "shared view" / guest-link feature require.

## Why this was NOT auto-fixed while you slept

There is no user→camera ACL model to filter against. Implementing one touches the auth layer,
the DB schema (a `user_camera_access` table or role/scope claims), every list endpoint, and the
WS fan-out. Shipping a rushed version unsupervised risks locking the owner out of their own
cameras or silently dropping events. This needs a deliberate design pass. Issue filed.

## Proposed design

1. **Model.** Add `user_camera_access` (user_id, camera_id) or a role with a camera scope set.
   Owners/admins get all cameras implicitly; restricted users get an explicit allowlist.
2. **Central helper.** `allowed_camera_ids(user, db) -> set[UUID] | ALL` reused everywhere
   (mirror Guardian's `_allowed_cameras`).
3. **List endpoints.** Add `.where(Camera.id.in_(allowed))` (skip when ALL) to events, recordings,
   observations, cameras.
4. **WS fan-out.** Tag each broadcast with its `camera_id`; in `_deliver_local`, drop messages for
   cameras the recipient can't see. Track each socket's user + allowed set at connect time.
5. **Media serving.** Enforce the same allowlist on recording/thumbnail/clip byte-serving
   endpoints (combine with `shared/paths` containment).
6. **Tests.** Restricted user sees only their cameras over REST and WS; owner sees all.

## Notes

- Coordinate with #23387 (hide-from-review) and the motion-search initiative — same allowlist.
- Until shipped, document clearly that Nurby is single-trust-domain (all logins are full-access).

## #201 read-surface audit (2026-09-23)

The central helper (`shared/camera_access.py`) and the first wave of scoping (#190)
covered search, timeline, summaries, conversations, transcripts, audio, digests,
notifications and the WS fan-out. A follow-up audit of the remaining authenticated
read surfaces found and fixed these cross-camera leaks:

- **`persons.py`** — `activity/summary`, `activity/{person_id}`, `clusters/activity/summary`,
  `clusters/activity/{cluster_id}`, `photo-candidates`, `starred/status` (via recap),
  `_auto_star_top_persons`, and the `follow` investigative bundle
  (`_follow_observations` + `_follow_bundle`: observations, incidents, transcripts).
  All now funnel through `allowed_camera_ids` + `apply_camera_filter` before the
  JSON scan, so a restricted viewer never sees a foreign camera's sighting,
  thumbnail, camera name, or last-seen location.
- **`vehicles.py`** — `activity/summary` and `activity/{vehicle_id}` scoped the same way.
- **`journeys.py`** — a journey aggregates incidents across cameras; it is now hidden
  entirely (fail-closed) unless every linked incident sits on an allowed camera.
  `list`, `get`, and `reinterpret` all enforce this; a foreign journey id returns 404.
- **`services/recap.py`** — `generate_recap`/`_collect_sightings`/`_latest_sighting_meta`
  take an `allowed` allowlist, threaded from `starred/status`.

Negative coverage: `tests/test_camera_read_scope_identity.py` drives these endpoints with a
restricted user (two cameras, one foreign) and asserts every emitted SQL statement carries
the `camera_id IN (...)` predicate, that a no-access user gets nothing, and that a foreign
journey id 404s.

### Remaining constraints (not yet covered — keep #201 open)

- **Query-token media byte-serving** (`persons/{id}/photo`, `vehicles/{id}/photo`,
  thumbnail/clip serving) authenticates with a shared query token, not a per-user
  session, so it cannot apply the per-user allowlist today. A restricted user who
  learns an object id could still fetch its image. Closing this needs the media layer
  to carry user identity (or per-camera signed URLs). Documented, not fixed.
- **Guardian** keeps its own facility/entitlement ACL and is intentionally out of this
  helper's scope.
- **Identity roll-ups** (`list_persons`, `list_vehicles`, cluster suggestion lists) still
  return globally-known identities; only their per-camera *activity* is scoped. Whether an
  identity seen only on a foreign camera should be hidden outright is a product decision.
