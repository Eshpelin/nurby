# Camera read scope — 17 September 2026

Continuation of [#201](https://github.com/Eshpelin/nurby/issues/201), built on the explicit access policy in [PR #202](https://github.com/Eshpelin/nurby/pull/202). This is a partial implementation of the release gate, not a completed security audit.

## Implemented

- Search and union search restrict observation, transcript, conversation and summary queries before ranking, limits and pagination. The vector, text, regex and recent-result fallbacks carry the same scope. Ask's people fallback also filters its evidence before model input.
- Timeline observations/transcripts are scoped. Household-wide mode-change notes are omitted for restricted viewers. On-demand timeline narration receives the allowed camera set, including an empty set; its existing scoped fact collector omits global journeys and vehicles.
- Stored digests and notifications with no camera ID are excluded for selected/none users because their content cannot be safely attributed to an authorized camera. Unrestricted users retain the existing behavior. Generated activity digests filter their source observations and omit global unknown-person enrichment for restricted viewers.
- Summary and conversation detail, conversation reinterpretation, transcript detail/edit/delete/export, notification reads and bulk read updates enforce the same camera policy. Conversation transcript joins also constrain the transcript's camera ID.
- Raw audio and conversation clips require an active account and camera access before filesystem reads. Both bearer credentials and query tokens are supported. The shared login-token decoder rejects pairing/guardian-claim tokens; their dedicated redemption flows remain unchanged.
- FindAnything validates its initial scope, searches only that scope, and rechecks current account access before each frame/cache read. Polling retained jobs checks current access too. Losing any original grant hides the entire retained job rather than disclosing counts or partial results. A request already in flight is not recalled.

## Validation

- Full backend suite: 2,314 passed, 3 skipped before the final two-user integration test was added.
- Updated camera-read suite: 56 passed, including real SQLite queries and HTTP requests using two users, two cameras, JWTs and an API key. Removing the final grant denies subsequent requests using existing credentials.
- PostgreSQL SQL compilation covers vector/text fallback filtering; real SQLite rows verify that a newer unauthorized result cannot consume the authorized user's page limit.
- Negative HTTP cases cover foreign IDs, evidence mutations, model triggers, media tokens and scan polling. A background-scan test revokes access before the next frame and verifies that neither its cache nor file is read.
- Python CI lint rules pass. These tests do not replace a live PostgreSQL integration run, live camera playback or deployment verification.

## Remaining release gate

1. Audit global identities, face/body clusters, person/vehicle details, journeys and their embedded cross-camera summaries. A row's primary camera is not sufficient evidence that every nested field belongs to that camera.
2. Audit remaining metadata, chat/tool routes, notifications outside these HTTP paths and untagged WebSocket payloads. The shared query helpers retain unrestricted defaults for existing internal jobs; every user-facing caller must supply scope explicitly.
3. Validate actual media ingress and playback. The checked-in MediaMTX configuration permits anonymous publish/read/playback/API actions. API-level filtering does not protect a reachable direct MediaMTX endpoint. Transport authentication, reverse-proxy exposure and web/mobile playback must be reviewed together.
4. Exercise all/selected/none users against the running deployment, including deactivation, grant removal, active sockets, browser/mobile media and API keys. Review shared artifacts and stored summaries for mixed-camera evidence.

No deployment or live database migration was performed. Keep #190 and #201 open until the entire access contract is demonstrated.
