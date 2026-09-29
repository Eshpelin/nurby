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

## Current audit status

The following product surfaces have now been audited and their user-facing
copy is catalog-driven, including loading, empty, error, action, and relevant
accessibility labels:

- dashboard, people, cameras, recordings, events, and camera settings;
- rule editors and trigger controls, including association, audio, speech,
  plate, parking, and geometry rules;
- pipeline, Ask Nurby, agent responses, onboarding, account/security, and
  error-boundary surfaces;
- activity, follow/journey, recap, live voice, incidents, and identity-review
  components.

The recordings audit was completed in commits `80bcf0c` and `0dc1984`, which
moved card metadata, evidence chips, storage status, pagination, accessibility
labels, and workflow error states into the catalog.

Remaining work is limited to a final repository-wide review for newly added
copy and any newly discovered literal labels. Model-generated answers,
camera/person/vehicle names, transcripts, provider names, server-provided
rule text, URLs, protocol labels, and other evidence/data values remain
intentional exceptions described below.

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
