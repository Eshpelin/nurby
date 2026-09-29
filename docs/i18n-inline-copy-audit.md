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
  Authentication, Danger Zone, package tracking, ONVIF/PTZ detection, PTZ
  controls, and privacy zones.

## Remaining user-facing surfaces

These contain inline labels, loading states, empty states, or actions that
should move to the shared English/Spanish catalog in follow-up slices:

- `frontend/src/app/page.tsx`: dashboard filters, search states, recap labels,
  and first-camera/no-results guidance.
- `frontend/src/app/people/page.tsx`: people, unknown-cluster, merge, and
  deletion dialogs.
- `frontend/src/app/cameras/[id]/page.tsx` and its remaining camera settings
  panels: AI analysis, detection, refiners, recaps, summarization, zones, and
  any page-level status or save feedback still containing product copy.
- `frontend/src/components/rules/TriggerSection.tsx` and related editors:
  rule labels, hints, option labels, and zone instructions.
- `frontend/src/app/recordings/page.tsx` and `frontend/src/app/events/page.tsx`:
  bulk actions, trim/reset controls, pagination, and result states.
- `frontend/src/app/pipeline/page.tsx`, Ask/admin, and run detail pages:
  operational table headings and loading/empty states.
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
