# Onboarding completion audit — 17 September 2026

The resumed task found phases 1–4 already implemented by another agent and merged in PRs #205–#208. The later revert was itself reverted on main. Rebuilding those phases would duplicate existing work. Issue #204 remains open and had no implementation progress recorded.

## Follow-up implemented

The activation UI linked “Open the alert clip” to a general rules page and confirmed only a goal string. Meanwhile a later event could replace the stored evidence without clearing an earlier confirmation, including a synthetic-to-real transition.

- Resolve the exact milestone event and its recording through an account-scoped, admin-only endpoint. Validate rule/camera association, recording ownership and file availability.
- Play that recording inline. The normal UI requires playback to begin before enabling the user's receipt/usefulness confirmation. Playback errors disable confirmation.
- Confirmation must include the reviewed event ID; mismatches, missing recordings and missing files fail closed. It is still a user's assessment, not an independent receipt from a remote notification provider.
- Keep a real delivered test stable while it is being reviewed. Starting a new test explicitly clears its evidence and confirmation. Scaffolding/rebinding a rule also clears the previous result.
- Ignore tests from another camera or before a goal is configured. Serialize milestone changes using a row lock.
- Preserve the first confirmation timestamp on repeated confirmation requests.
- Add refresh/retest controls and reset the review component on goal changes.

No database migration is needed. Deploy the web/API updates together: confirmation now requires `event_id`. Previously stored confirmations are not a substitute for a fresh live validation; this change does not reconstruct historical playback or delivery receipts.

## Validation

- Full backend suite: 2,385 passed, 3 skipped.
- Full web suite: 57 passed.
- Production Next.js build and TypeScript checking passed. The isolated checkout reused installed dependencies, so the local production build used webpack; GitHub runs the normal build.
- Python CI lint and diff checks passed. Four pre-existing unused imports were removed to restore the lint gate.
- The production build also exposed an invalid exported constant in the rule-create page; the constant now lives in a shared module.
- No physical camera test, remote delivery receipt, deployment or live database change was performed.

## Remaining acceptance gaps

Keep #193 and #204 open. The implementation is substantial, but “all phases merged” is not proof that every original acceptance criterion is complete.

1. **Delivery provenance:** activation recording is currently wired to the in-app notify action; successful broadcasting is not proof that a particular recipient received it. Other delivery channels need their own measured outcomes. The confirmation in this patch explicitly asks the user to attest receipt.
2. **Starter consistency:** the after-hours web preview references the office template (7 pm–6 am with AI verification), while activation scaffolding maps to the night starter (10 pm–6 am without that verification). Align the preview, draft and capability requirements before treating this path as validated.
3. **Metrics meaning:** `install_ready_at` is populated when scaffolding/configuring a goal, not from a separately measured server-ready event. Seven-day abandonment and aggregate counts are implemented; cohort retention, noisy-rule disablement and actual user research remain incomplete under #199.
4. **Configuration provenance:** rule/camera rebindings reset this test, but edits to a rule in place are not versioned against the milestone. Historical confirmations and retained/deleted evidence need an explicit policy before broader rollout.
5. **Original wider plan:** a place label is not a multi-site workspace model. Invitation context and validated facility/staff workflows remain follow-up work.
6. **Live acceptance:** run a real-camera event through delivery, playback and confirmation, then test missing footage, failed delivery, a synthetic event and a repeat test. Do not infer customer validation from the automated suite.

The original shared checkout contained active MQTT and other work. This fix was implemented in a separate checkout and does not include those changes. PR #228 already covers structured alert feedback, so avoid duplicating that work as the next task. The P0 camera-isolation audit (#201) remains a release priority.
