# Frontend inline-copy audit

This is a living inventory for #265. It records user-visible strings that are
still written directly in JSX/TSX so localization work can be sequenced
without treating technical values or model-generated content as translatable
UI copy.

## Completed in the current localization pass

- `frontend/src/components/ExpectedActivityCard.tsx`
- `frontend/src/components/DailyPriorities.tsx`
- `frontend/src/components/DailyDigestCard.tsx`
- person/follow feed, WHEP player, conversation card, moment modal, alert
  feedback, devices, vehicles, and the existing settings slices documented in
  the #265 issue history.
- camera settings: General, Feed, YOLO-World prompts, Audio Conversations,
  Incident Tracking, Relationship Privacy, Timezone, Retention, Storage,
  Authentication, AI Analysis, Detection, Activity Digest/recaps, Danger Zone,
  VLM Refiner, Summarization, package tracking, ONVIF/PTZ detection, PTZ
  controls, privacy zones, and the ZoneEditorCanvas controls.
- rule trigger chooser: trigger-card labels/descriptions, object confirmation
  and movement controls, named-area scoping guidance, audio and speech
  controls, plate-list and parking controls, and geometry-trigger camera,
  drawing, subject, threshold, direction, and wrong-way guidance.

## Remaining user-facing surfaces

These contain inline labels, loading states, empty states, or actions that
should move to the shared English/Spanish catalog in follow-up slices:

- `frontend/src/app/page.tsx`: dashboard filters, recap/AI states,
  live/search-result labels, event-card labels, and first-camera/no-results
  guidance are catalog-driven for the audited surface. Re-open only when a
  new dashboard surface is added.
- `frontend/src/app/people/page.tsx`: some activity-card and reference-detail
  copy remains; person and unknown-cluster suggestion cards, forms, merge,
  photo, consent, deletion-reference, and primary row actions are
  catalog-driven.
- `frontend/src/app/cameras/[id]/page.tsx` and its camera settings panels are
  catalog-driven for the audited product copy. Re-open this entry only when a
  new camera-facing surface is added.
- `frontend/src/components/rules/TriggerSection.tsx` and related editors:
  association controls remain to be audited; the trigger-specific audio,
  speech, plate, parking, and geometry slices are catalog-driven above.
- `frontend/src/app/recordings/page.tsx` and `frontend/src/app/events/page.tsx`:
  bulk-action result states, remaining recording-card metadata, and some
  pagination/result copy remain; filters, download/share, trim/reset, and
  review-control labels are catalog-driven.
- `frontend/src/app/pipeline/page.tsx`, Ask/admin, and run detail pages:
  operational table headings, status labels, errors, and loading/empty states
  are catalog-driven. Ask Nurby’s main page, provider fallback, history rail,
  and empty state are now catalog-driven. ChatComposer, model/cost controls,
  deep-scan warnings and actions, and onboarding modal copy are also
  catalog-driven. AgentResponseCard status, trace, citation, completion,
  inspector, and safety labels are catalog-driven; model-generated answers,
  tool names, and evidence text remain intentional data/technical exceptions.
- `frontend/src/components/IncidentCard.tsx`, `PersonActivityModal.tsx`,
  `ZoneEditorCanvas.tsx`, `PTZControlPanel.tsx`, and `LiveConversationCard.tsx`:
  activity, camera-control, and live-audio copy.
- `frontend/src/components/SecureAccountModal.tsx`, error boundary, and
  onboarding/first-use surfaces.

## Intentionally not catalog-driven

- Camera names, person names, vehicle plates, provider names, transcripts,
  model-generated summaries, and server-provided rule/priority text are data,
  not product copy.
- URLs, API paths, environment variables, code examples, model names, and
  protocol labels remain literal technical text.
- `aria-label` values and image alt text are included in the localization work
  when they describe a product action or state; identifiers and raw evidence
  descriptions remain data-driven.

## Completion rule

The issue can close only after each remaining user-facing surface is either
catalog-driven or explicitly documented as an intentional exception, with the
catalog validation, TypeScript check, and frontend suite passing.
