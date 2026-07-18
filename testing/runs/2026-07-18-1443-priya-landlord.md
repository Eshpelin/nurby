# Priya, 45 — landlord, 4 units (2026-07-18)

Tech: medium, spreadsheet person, values audit trails. Goals: add cameras
for 4 entrances, invite each tenant with viewer access limited to their
own camera, verify an invite key actually restricts what the tenant
sees (by logging in as the tenant herself), review who has access and
revoke one.

## Narrative

Logged in as Priya (seeded admin). Added four cameras via Manage →
Settings → dashboard "+ Camera": Unit 1–4 - Front Door, all pointed at
the `lobby` feed pool (shared test clip, distinct names — matches how a
landlord would label four units off the same footage type). Confirmed
all seven cameras (3 inherited + 4 new) show up and start producing
detections.

Went to Settings → Invite Keys → Manage, created a Viewer-role key
scoped to only "Unit 1 - Front Door" via the Camera Access checkbox
grid, max uses 1. Logged out, redeemed the key at `/invite` as a new
account "Raj (Unit 1)" — this is the actual product invite flow, not
the seeder, so it's a real first-time-tenant test.

As Raj, the camera wall correctly showed only Unit 1's tile
(`/api/cameras` and live-detections requests only referenced Unit 1's
camera id — confirmed via network log). But the Morning Brief digest
at the top of the dashboard listed bullets naming "Demo Camera" and
"Front Door" — cameras Raj has no grant to. Regenerating the brief
reproduced it again with fresh timestamps, ruling out stale cache.
Pulled the raw `/api/incidents` response and found camera_ids
belonging to other cameras entirely, with full observation-id lists and
thumbnail file paths — a real data leak, not just a copy problem.

As Priya again, reviewed Settings → Camera access (the actual
per-user audit view Priya's persona explicitly wants — shows each
non-admin user and their grants at a glance, exactly the "review who
has access" ask). Found Raj correctly listed with exactly 1 of 7
cameras granted. Tested "revoke": toggling off Raj's only granted
camera did NOT restrict him further — the UI's own documented policy
copy says revoking someone's last grant returns them to seeing ALL
cameras. Confirmed by revoking and re-checking: "No grants · this user
currently sees all cameras." For a persona who explicitly said "I test
permissions by logging in as the tenant myself" and would very
plausibly click that toggle intending to lock a tenant out, this is a
trap that does the opposite of what "revoke" reads as.

## Findings

- **F73 · blocker · security** — `/api/incidents` (list, single-get,
  reinterpret) had zero camera-access-grant filtering, unlike every
  other camera-scoped endpoint (`observations`, `cameras`, `events`,
  `recordings`, `ws`). A restricted viewer could see incident rows —
  including full observation-id lists and thumbnail file paths — from
  cameras they have no grant to, and could fetch/reinterpret any
  incident by guessing/enumerating its UUID regardless of scope.
  Fixed: `services/api/routes/incidents.py` now uses the same
  `allowed_camera_ids`/`apply_camera_filter` helper as the rest of the
  API; added `_get_incident_in_scope` used by both the single-get and
  reinterpret routes to 404 (not 403, to avoid confirming existence)
  incidents outside the caller's grant.

- **F74 · major · security** — The Morning Brief / daily digest served
  the same household-wide cached row to every user regardless of
  camera grants, so a restricted viewer's digest named cameras outside
  their scope ("Demo Camera", "Front Door"). Root cause: the digest
  worker builds one global `DailyDigest` row with no per-user concept
  at all — `_collect_facts` had no camera filter, and the API route
  just returned the latest row to whoever asked.
  Fixed: `_collect_facts()` in `services/perception/daily_digest.py`
  now takes an optional `camera_ids` filter, applied to observations,
  incidents, audio, conversations, and the camera-name lookup;
  vehicles and journeys are cross-camera by nature and are omitted
  entirely (not filtered) for a scoped digest rather than risk a leak
  through them. `services/api/routes/daily_digest.py`'s three routes
  (`GET`, `GET /history`, `POST /run`) now check
  `allowed_camera_ids`: an unrestricted/admin caller gets the existing
  persisted household digest unchanged (no regression — verified as
  Priya after the fix, still sees the full household brief); a
  restricted caller gets a fresh, unpersisted, facts-only digest
  (skips the VLM narrative, matching the existing "facts only (no
  LLM)" mode the frontend already renders) scoped to their grants.

- **F75 · major · UX trap** — Revoking a user's *only* camera grant in
  Settings → Camera access doesn't restrict them further, it flips
  them back to "sees all cameras" (documented, intentional
  fail-open-for-single-owner policy) — the opposite of what an admin
  clicking "revoke" on a tenant's last camera would expect. Exactly
  the scenario Priya's persona goal describes.
  Fixed: `frontend/src/app/settings/access/page.tsx` now confirms
  before toggling off a user's last grant, naming the camera, the
  user, and explicitly stating they'll see all N cameras instead of
  none. Verified in-browser (stubbed `window.confirm` to inspect the
  message and to cancel, then confirmed the grant was untouched).

- **F76 · minor · polish · dashboard** — The wall toolbar's "+ Camera"
  / "+ Widget" quick-action buttons are intermittently unclickable at
  some viewport heights: `CameraWall`'s `flex-1 min-h-0` root collapses
  to zero height when `SetupChecklistCard`/`AskComposerCard` above it
  consume the available space, and without `overflow-hidden` anywhere
  in that chain the toolbar visually spills out below its own box and
  lands in the same screen region as the `SystemHealthFooter`, which
  wins the hit-test since it's later in the DOM. Reproduced 3
  consecutive real-click misses in this run; worked around with
  `element.click()` via JS to keep testing moving. Root-caused (see
  file:line detail in this run's investigation) but not fixed —
  needs a real height-budget fix in `CameraWall.tsx`/`page.tsx`
  (bound the grid's height and let it scroll, or give the toolbar row
  `overflow-hidden` at the wrapper level), left for the next run.

- **Deferred, not filed as its own F#** — the Invite Keys management
  panel lists each key's role/uses/expiry but not which cameras it's
  scoped to, so an audit-minded admin (this persona explicitly said
  "values audit trails") can't tell from that list alone what a given
  key grants without re-testing it. Minor; noting for backlog.

## Working well

- priya-landlord, 2026-07-18: adding four cameras back-to-back via the
  dashboard's "+ Camera" quick action worked cleanly once clicked
  (each immediately started producing detections).
- priya-landlord, 2026-07-18: the invite-key camera-scope picker (role
  + max uses + expiry + a checkbox grid of every camera) is exactly
  the right shape for "give this one tenant access to just their
  camera" — straightforward to use once reached.
- priya-landlord, 2026-07-18: Settings → Camera access is a genuinely
  good per-user audit view — one screen answers "who can see what"
  for every non-admin user, which is exactly what this persona wanted
  without having to reverse-engineer it from invite keys.

## Product verdict (Priya's voice)

"The pieces are all here — scoped invites, a real audit screen — but I
found two things that would have burned me for real: my tenant's brief
was naming my other units by name, and revoking someone's camera would
have opened everything to them instead of shutting them out. Glad I
tested by logging in as him first, like I always do."
