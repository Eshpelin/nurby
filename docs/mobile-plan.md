# Nurby Mobile (Flutter) Plan

Cross-platform Flutter app (iOS + Android from day one) mapping the Next.js web app 1:1 where mobile-sensible. Lives in `mobile/` in this repo. Package: `com.nurby / nurby_mobile`.

## Architecture

- **State**: Riverpod. One `ApiClient` (Dio + JWT interceptor), repositories per resource, providers per screen.
- **Navigation**: go_router with a bottom-nav shell (Cameras, Timeline, Ask, Alerts, More). Secondary screens (Rules, People, Vehicles, Recordings, Search, Settings, Guardian) hang off "More" and deep links.
- **Server pointer**: self-hosted server, so first-run screen asks for server URL (stored in SharedPreferences). Token in flutter_secure_storage.
- **Auth**: mirrors web: needs-setup check, setup / login / register-with-invite, 401 clears token and routes to login. No refresh endpoint; re-login on expiry.
- **Realtime**: `WS /ws?token=` with capped exponential backoff (1..30s). Message types consumed: `event`, `notification`, `event_fired`, `vlm_status`, `detection`, `incident*`, `transcript_created`. Drives timeline refresh, badges, live overlays. Agent Q&A uses `WS /ws/agent/{run_id}`.
- **Polling fallback**: cameras 10s, timeline 15s (matches web).

## Live video strategy

| Stream type | Mobile rendering |
|---|---|
| rtsp (via MediaMTX) | WebRTC WHEP (`flutter_webrtc`, POST SDP to `:8889/{name}/whep`) with HLS fallback (`video_player`, `:8888/{name}/index.m3u8`) |
| file / http(s) demo | `video_player` direct URL, looped, muted |
| webcam / snapshot | poll `/api/cameras/{id}/frame` JPEG at ~1fps |
| audio_only | static tile with indicator |

Detection overlay: CustomPainter over the video, boxes from WS `detection` / `person_actions` messages, normalized to frame size. Fade after inactivity.

## Screen map (web → mobile)

| Web | Mobile |
|---|---|
| Dashboard camera wall + timeline panel | Cameras tab (grid of live tiles, status, latest activity) + Timeline tab |
| /timeline | Timeline tab: merged observations + transcripts, filters (camera, time), detail sheet with thumbnail + VLM text |
| /events | Alerts tab: event history, severity, ack / batch ack, filter |
| /rules (+new/edit) | Rules screen: list, enable/snooze, form editor (trigger, conditions, actions), NL "describe rule" generator |
| /people | People screen: known persons + activity, face-cluster suggestions (name / ignore) |
| /vehicles | Vehicles screen: list, edit nickname/plate |
| /recordings | Recordings screen: list + inline MP4 playback (`?token=`) |
| /search | Search screen: query + filters, results grid, "Ask" answer panel |
| /ask | Ask tab: agent chat with WS streaming, run history |
| /settings | Settings: server/account, providers CRUD + test, system status/doctor/storage, SMTP, invites, users (admin) |
| /guardian | Guardian screen (guardian-role users): links, status, timeline |
| /setup, /login | Server URL → setup-or-login flow |
| Camera detail | Camera detail: live view, PTZ, config sections (detection, VLM, recording, retention, privacy), activity |
| Onboarding wizard | Trimmed: add-first-camera prompt (demo camera button + RTSP form) |

Web-only, deliberately skipped in v1: browser-webcam publisher, browser-mic publisher, widget builder, zone-drawing canvas (view-only), traffic-signal zones, reports scheduling UI (list/run only), pose-skeleton overlay (boxes only).

## Design

Dark-first, near-black background (#0A0A0A), card #0E0E0E, border #262626, green accent hsl(142 71% 45%) = #20C05C, red danger, amber warning. Mono font for timestamps/IDs (SF Mono / Roboto Mono). Material 3 with custom ColorScheme, no light mode in v1 (web defaults dark).

## Build order

1. Core: config, ApiClient, models, repositories, theme, router, auth screens. ✅ started
2. Shell + Cameras tab (grid, tiles, WHEP/HLS/poll rendering, overlay).
3. Timeline + Events (+ack) + notifications badge + WS client.
4. Rules (list + editor + NL), People (+clusters), Search + Ask (agent WS).
5. Recordings, Vehicles, Camera detail/settings, Settings cluster, Guardian.
6. Tests: unit (models, repos with mocked Dio), widget (login, cameras grid), `flutter analyze` clean, iOS sim run against local docker backend.

## Risks

- WHEP handshake needs MediaMTX reachable from phone; app takes full server URL so LAN IP works. HLS fallback covers WebRTC failures.
- Android toolchain on this machine missing cmdline-tools; iOS is the verified target, Android compile checked via `flutter build apk --debug` once tools fixed (best effort).
- No native push in backend; alerts arrive via WS while app open. Documented gap for later (FCM/APNs would need backend work).
