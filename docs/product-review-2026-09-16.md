# Nurby product review — 16 September 2026

## Recommendation

Make Nurby the private camera assistant that tells people what needs attention, shows the evidence, and helps them respond. Prioritize a dependable end-to-end monitoring experience over additional detection categories.

The strongest product assets are local ownership, people-aware search, cross-camera journeys, explainable automation, and scoped Guardian access. The biggest product risk is breadth: home security, family care, facility monitoring, traffic, industrial automation, voice, and developer infrastructure each imply different buyers, reliability expectations, and onboarding.

**Recommended initial audience:** technically capable households with existing IP cameras, particularly people monitoring their home while away. Treat this as a hypothesis to validate, not an established market finding. Their installation tolerance fits the current self-hosted distribution. Small businesses are an adjacent pilot; Guardian needs its own facility-validation track. Do not give all three equal roadmap weight until usage and buyer evidence justify it.

## Basis and limits

This is a repository-based product assessment, covering the README, product/design documents, historical UX findings, current web/mobile structure, and selected implementation paths. It is not a new live usability test, security audit, production reliability measurement, or customer study. Existing persona tests are useful scenario coverage, not evidence of market demand. Mocked agent evaluations do not establish real-camera answer accuracy.

Current code takes precedence over older plans. The September navigation consolidation, Home/Away/Night modes, incident grouping, scheduled questions, invitation page, citation validation, workplace templates, and worker-health warnings already exist. Recommendations below extend those capabilities rather than propose them as missing.

## Use-case assessment

| User and job | Existing foundation | Recommended next change | What success means |
|---|---|---|---|
| Homeowner: know what happened while away | Cameras, alerts, modes, recaps, mobile | Prove an alert arrives off the home network; show monitoring coverage | User receives an actionable alert and opens its clip on cellular |
| Household: investigate a delivery or visitor | Ask, recordings, semantic search, journeys | One answer card with scope, evidence, and explicit gaps | Correct moment found without manual timeline hunting |
| Pet owner: find a pet or unusual activity | Animal detections, open-vocabulary search, rules | Pet-specific setup, user corrections, clear limits on individual recognition | Relevant activity found with few nuisance alerts |
| Family caregiver: check a relative's recent activity | People, last sightings, Guardian, audio signals | Distinguish last observed activity from current wellbeing; configure check-in response | Family knows when evidence is stale and who will follow up |
| Parent/facility: arrival and pickup | Guardian grants, blur, registry, inferred escort | Separate camera inference from staff-confirmed handover | Every confirmation identifies its evidence or staff confirmer |
| Shop operator: review after-hours activity | Schedules, zones, incidents, alerts, export | Business-hours setup, incident ownership and resolution | Staff can close an incident without duplicate work |
| Workplace operator: automate a response | Sequence rules, API actions, device templates | Shadow mode, approval for consequential actions, result receipts | Each action is traceable and failed/retried actions are visible |
| Builder: connect existing systems | REST, MCP, signed webhooks, device integrations | A few tested recipes with diagnostics and compatibility limits | A supported integration works without designing payloads from scratch |

## 1. Fix permission behavior before expanding shared deployments

**Observed:** `shared/camera_access.py` returns unrestricted access for a non-admin with zero explicit grants. The historical findings describe a confirmation dialog added when revoking a user's final grant. That warns about the behavior but leaves the underlying product contract surprising.

**Change:** introduce explicit access states: all cameras, selected cameras, no cameras. Removing the last selected camera must leave no access. Migrate existing users explicitly so intended access survives the policy change. Show an effective-access preview to the administrator.

**Acceptance:** revoking a final camera grant cannot broaden access. Verify the same policy on footage, thumbnails, live streams, search, recaps, exports, and live updates. This recommendation concerns the general camera policy; it does not claim Guardian's separate scoped routes all leak data.

**Priority:** P0, before wider multi-user pilots.

## 2. Make Guardian's wording match the strength of its evidence

**Observed:** `services/guardian/pickup.py` infers an escort from frequently co-present people and vehicle plates near departure. `alerts.py` checks the result against the approved registry and can generate “was picked up by…” wording. Nearby presence and a matching plate do not establish an actual handover.

**Change:** use three distinct states: “Possible pickup detected,” “Approved person/vehicle matched,” and “Pickup confirmed by staff.” Record who confirmed, when, and any correction. Conflicting or weak evidence stays pending. Preserve blurred evidence and immediate revocation.

For eldercare, show “Last seen in kitchen at 09:42; camera online” rather than implying a wellbeing assessment from presence alone. Let families define expected check-in windows and a contact/escalation path.

**Acceptance:** no inferred pickup is labeled staff-confirmed; stale sightings and unavailable monitoring are visible; a facility can correct an event without erasing its history.

**Priority:** P0 for Guardian expansion. Start with presence and communication workflows; validate stronger claims separately.

## 3. Finish onboarding with proof of value

**Observed:** the setup checklist marks progress from camera/provider/rule/channel configuration. A configured channel or active rule is not proof that the intended user received an alert.

**Change:** begin with “What do you want Nurby to tell you?” Offer a small set of goals: someone at the door, activity while away, find footage, or check on a person. Recommend a camera, zone, rule, and delivery path for that goal. Keep model catalogs and tuning under Advanced.

Finish with a guided real-world test: walk through the selected zone, receive the alert, open the clip, and confirm it was useful. A synthetic test should be clearly labeled and should not stand in for this real-camera test. Make optional AI setup optional in completion criteria for detection-only use cases.

**Acceptance:** the checklist distinguishes configured, tested, and confirmed by user. Show separate timings for installation and first useful result after the server is ready.

**Priority:** P1. Reuse the existing wizard, templates, and checklist.

## 4. Turn system health into understandable monitoring coverage

Worker-health banners and the doctor are already valuable. Extend them into a coverage contract visible on Home, in recaps, and in Ask results.

Show whether video is arriving, recording is available, detection is running, AI analysis is current, and notification delivery is working. Include the latest successful timestamp for each relevant step. A healthy live stream does not prove historical analysis was complete.

Example: “No relevant activity found in the footage analyzed. Driveway recording unavailable from 02:10–02:34.” Keep coverage scoped to the user's permissions. Never turn a missing feed into “all quiet.”

**Acceptance:** introduce a deliberate camera, model, or delivery outage and verify that the relevant product surface describes the missing capability and affected interval.

**Priority:** P1. Build on existing health and outage handling.

## 5. Make remote mobile use a core acceptance test

**Observed:** a remote-access design exists, while the reviewed mobile live-view implementation still constructs separate streaming-port URLs. I did not verify any deployed remote installation.

**Change:** complete a guided remote path with one public entry point, clear authentication requirements, stream fallback, and a cellular connectivity test. Diagnose “server unreachable,” “notification delivery unavailable,” and “video cannot play” separately. Expose paired-device revocation in the same journey.

**Acceptance:** on cellular, receive an alert, open its exact clip, view the camera, and acknowledge it. Verify expired sessions, server restarts, and a network that blocks the preferred live-video transport.

**Priority:** P1. “Know what happened while away” depends on this working end to end.

## 6. Add a structured alert-improvement loop

**Observed:** alerts have acknowledgment, mute, action status, and notes. The reviewed event model/routes do not expose a structured correctness/relevance feedback workflow.

**Change:** distinguish “Useful,” “Correct but not useful,” and “Incorrect.” For incorrect alerts, ask one optional reason: wrong object, wrong person, duplicate, or wrong timing. Acknowledgment should continue to mean seen/handled, not correct.

After enough reviewed examples, suggest a specific change with a historical preview: “This zone change would have removed 8 reviewed nuisance alerts and retained 5 useful ones.” Explain that historical replay cannot prove future recall. Apply changes only when accepted; allow undo.

**Acceptance:** users can correct an alert in two taps; suggestions show affected examples; no hidden threshold changes. Measure both nuisance reduction and missed events using labeled scenarios.

**Priority:** P1 for feedback capture; P2 for tuning suggestions.

## 7. Close the review-to-resolution journey

Keep the five-place navigation introduced in September. Further improvement should happen inside the workflow, not through another navigation redesign.

Build a consistent detail view shared by Activity and Ask: summary, exact clip, related sightings, why an alert fired, action result, and next action. Reuse existing incident grouping. Default Home to unresolved important alerts and monitoring issues, with recaps and camera access directly below.

For households, add a lightweight resolved/dismissed distinction. For business pilots, add assignment, resolution reason, and an evidence bundle containing selected clips, timestamps, and notes. Clearly distinguish “I saw it” from “I dealt with it.”

**Acceptance:** a user can understand, inspect, and resolve a relevant incident without hunting across several pages; shared users see who handled it.

**Priority:** P2; do the household version first.

## 8. Give Ask Nurby a verifiable answer format

Citation validation already exists. Improve the user-visible contract around it: answer, camera/time scope searched, supporting moments, and limitations. Label a named person's match, an uncertain identity, and an unidentified person differently.

Let a successful question become an existing scheduled question or open a prefilled alert-rule draft. Always make the saved state explicit; conversational intent alone must not look like successful activation.

Validate with real footage containing known answers: deliveries, repeated visitors, ambiguous faces, missing recording periods, nighttime scenes, and no matching event. The current mocked 30/30 report is useful regression coverage, not an accuracy claim.

**Acceptance:** users can inspect the evidence for material claims, see search scope changes, and understand why an answer is incomplete.

**Priority:** P1 for scope/uncertainty; P2 for saved-question handoffs.

## 9. Validate business automations before selling the template promise

Workplace templates now exist, including a guest-fee template based on a tripwire and a subsequent person detection. That is insufficient evidence by itself to market verified unauthorized entry or automatic billing. The template's current second step does not itself express a distinct second entrant tied to an access-control authorization.

Make these templates create a reviewable candidate incident first. Add shadow mode, clear prerequisites, duplicate prevention, and an action receipt that distinguishes requested, succeeded, failed, and awaiting approval. “Guest fee raised” should depend on a confirmed downstream result.

Generic HTTP support is integration infrastructure, not proof that a vendor workflow works. Select two or three integrations requested by pilot customers and validate authentication, payloads, retries, and error recovery.

**Priority:** P0 to constrain consequential template claims/actions; P2 for validated business workflows.

## Delivery order and measurement

These are sequencing recommendations, not engineering estimates. Confirm capacity and architecture before assigning dates.

| Window | Focus | Exit evidence |
|---|---|---|
| First 30 days | Permission semantics, Guardian wording, consequential-template review, activation instrumentation | Revocation never broadens access; inferred states are explicit; activation funnel is measurable |
| Days 31–60 | Real alert setup test, coverage visibility, remote mobile path, structured feedback | Pilot households receive and inspect real alerts off-LAN; outages and corrections are understandable |
| Days 61–90 | Evidence-to-resolution flow, tuning suggestions, one narrow business or Guardian pilot | Repeat use and useful outcomes improve without a rise in missed events or support burden |

Track activation as a real camera producing a relevant event that the intended user receives and opens. Measure retained monitoring as installations still operating and providing user-confirmed value after four weeks; daily app opens alone are a poor target for a product meant to quietly monitor.

Supporting measures: setup completion/drop-off, useful-alert share among reviewed alerts, nuisance alerts per camera-day, alert-to-playable-clip success, time to locate a known event, recording/analysis coverage, incident resolution time, and support time per install. Keep feedback response rate beside usefulness metrics to expose selection bias. Establish baselines before setting percentage targets. Prefer local instrumentation with explicit opt-in for shared analytics; do not collect footage for product analytics by default.

## Commercial and discovery choices

Keep the local open-source experience coherent. Test willingness to pay for managed convenience—supported installation, remote connectivity, backup, or fleet administration—before adding billing. For Guardian, the facility is the likely buyer and administrator while the family is the daily user; interview both. These are business-model hypotheses, not validated demand.

Recruit a small first round of real households, shop operators, and facility staff/guardians. Observe installation, one useful alert, one footage question, and one failure. Revisit after a week. Choose the next segment based on repeat use, support burden, and willingness to adopt/pay, rather than positive demo reactions.

Defer broad industrial metrics, automatic financial actions, a general notes graph, and more model choices until the main monitoring loop is dependable. These can become valuable later; they currently spread attention across different products.

## Market context

AI descriptions alone are not a sufficient positioning claim: Frigate documents review summaries, and Scrypted documents AI summaries in notifications and its Stories view. Nurby's stronger candidate distinction is the combined experience of private ownership, people-aware evidence, useful answers, and controlled actions. This is a strategic interpretation, not a comprehensive competitor comparison.

- [Frigate review workflow](https://docs.frigate.video/usage/review/)
- [Frigate AI review summaries](https://docs.frigate.video/configuration/genai/genai_review/)
- [Scrypted NVR features](https://docs.scrypted.app/scrypted-nvr/features.html)

## Repository evidence

- `README.md`: product promise, installation, use cases, Guardian claims.
- `docs/ia-rollout.md`, `frontend/src/components/MegaNav.tsx`: current navigation and vocabulary.
- `docs/household-mode.md`: shipped manual modes and explicit non-goals.
- `shared/camera_access.py`, `testing/FINDINGS.md`: zero-grant access behavior and prior warning-only fix.
- `services/guardian/pickup.py`, `services/guardian/alerts.py`: escort inference, registry matching, notification wording.
- `frontend/src/components/SetupChecklistCard.tsx`, `services/api/routes/system.py`: setup completion criteria.
- `frontend/src/app/page.tsx`: health warnings, recap, grouped activity, setup entry points.
- `docs/remote-access-design.md`, `mobile/lib/features/cameras/live_view.dart`: remote design and current media URL construction.
- `shared/models/rules.py`, `services/api/routes/events.py`: alert acknowledgment, action status, notes.
- `frontend/src/lib/rule-templates.ts`: existing workplace templates and guest-fee action chain.
- `services/agent/driver.py`, `docs/agent-reasoning-gaps.md`, `.eval-report.md`: citation validation and evaluation limits.
- `docs/industrial-automation-plan.md`, `docs/notes-knowledge-plan.md`: expansion proposals, not assumed shipped wholesale.

No application behavior was changed for this assessment.
