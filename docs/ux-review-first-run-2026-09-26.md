# First-run UX review — 26 September 2026

Method: an isolated fresh install (new Postgres DB `nurby_ux2`, dedicated API
container on :8788, dev frontend on :3001, shared MediaMTX/Redis with the
existing dev stack) was driven in a real browser as a brand-new semi-technical
user: empty dashboard → setup → demo camera → camera workspace → rules →
settings → ask → people. Every finding below was observed live (screenshots in
`docs/screenshots/ux-review-2026-09-26/`) or pinned to code. Prior art
(`docs/ux-review-2026-07-12.md`, `docs/onboarding-review.md`,
`docs/onboarding-completion-audit-2026-09-17.md`) was checked; fixed items are
not repeated.

Goal of the review: can a new user who knows nothing about households, rules,
or AI providers add a camera and reach value without hand-holding?

---

## A. First-run and onboarding

**A1 [P0] The guided first-run wizard never auto-opens.**
`docs/` README tells users the first visit "drops you straight in" with a
"Show me some magic / Set it up myself" choice. In reality a fresh install
lands on the dashboard with four warnings and no wizard. The wizard
(`OnboardingWizard`) mounts only when `showWizard` is true, and the only
`setShowWizard(true)` call site is the "Set up a camera" button *inside* the
launcher popover (`frontend/src/app/page.tsx:2176`,
`frontend/src/components/GettingStartedLauncher.tsx`). The actual entry surface
is a small "🚀 Set up Nurby" pill in the bottom-left corner — easy to miss, and
it opens a *different* wizard (goal/rule/test), not the welcome one.

**A2 [P1] The path to the welcome screen is four clicks deep and out of order.**
Observed sequence to reach "Welcome to Nurby": launcher pill → "Continue"
(goal step) → "Set up a camera" (switches wizards) → "Continue" (storage step)
→ then finally "Welcome / magic vs manual". Storage is asked before the
welcome; goal/rule questions are asked before a camera exists. The wizard
itself says "Start here. Connect a camera, then come back to this step" —
a linear flow that redirects the user out and back.

**A3 [P1] The SetupWizard coachmark covers the button it is about.**
On step 2 ("Set up the rule"), the Coachmark tooltip overlaps the primary
"Create the draft rule" button (screenshot `02-setup-step2.png`).

**A4 [P1] Magic downloads the biggest RAM-fitting model and ignores models the
user already has.**
`_recommend_model` (`services/api/routes/ollama_deploy.py:172`) walks
`VISION_MODELS` in catalog order (Gemma 4 first) and picks the first entry
whose `ram_gb * 1.5` fits system RAM. It never consults the already-installed
model list it just fetched. Observed: host Ollama already had `gemma3:4b`
(3.3 GB) and `moondream`, yet magic started an **8.5 GB** `gemma4:12b` download
with no size shown ("Starting download of gemma4:12b", progress "–", frozen
bar). On this Ollama the pull then failed with `ollama_outdated`, leaving the
stale "Starting download…" message on screen for tens of seconds before any
fallback. README itself recommends `gemma3:4b` for Macs ("10–20× faster").

**A5 [P2] Storage step copy is for power users, shown to everyone.**
Duplicate heading ("Where should recordings be stored?" twice), and an amber
block referencing `.env`, `NURBY_RECORDINGS_VOLUME`, and a docs path inside the
first-run modal (screenshot `01-wizard-storage.png`). The "Check" affordance
and "Use this location" vs "Continue" duality is unclear.

**A6 [P2] Two wizards with overlapping purpose and separate entry points.**
`SetupWizard` (goal → rule → test → confirm, popover) and `OnboardingWizard`
(storage → welcome → camera → provider, modal) are both reachable from the
dashboard and reference each other ("Set up a camera", "come back to this
step"). New users cannot build a mental model of "setup".

## B. Dashboard first impression

**B1 [P1] Fresh install opens with a red "Not recording" alarm.**
Zero cameras, nothing configured, and the page shows a red banner ("Not
recording: video ingestion and AI perception are stopped… alerts won't fire")
plus a red navbar badge. Nothing is wrong; the user simply hasn't added a
camera. The banner text even contradicts itself ("Your cameras are fine" —
they have none). Alarms should be calm/neutral until there is at least one
real camera. (screenshot `00-first-run.png`)

**B2 [P2] Floating UI overlaps.**
- The "One step left / Secure your account" card overlaps the Ask composer
  (top-right) on 1440×900 (screenshot `00-first-run.png`).
- The "Add AI descriptions" hint card overlaps the "Set up Nurby" launcher
  pill (bottom-left, screenshot `04-after-magic.png`).
- The autosave toast overlaps the launcher pill on the camera page
  (screenshot `06-camera-workspace.png`).
Three red "secure account" surfaces exist simultaneously (navbar button, nudge
card, one-step-left card).

**B3 [P2] Context-free suggestions on an empty install.**
- Timeline empty state offers "Try last 30 days" on a 5-minute-old install.
- "Try asking Nurby" chips (What happened today? / Was anyone at the door? /
  Where's the dog right now?) are shown when no AI provider is configured, so
  every one of them fails (Ask page itself handles this well — the dashboard
  card does not).
- Wall toolbar exposes Fullscreen/Reset/grid-size for an empty wall; the
  actual "Connect your first camera" empty state is relegated to the right
  rail while the main area is a big black void.

**B4 [P2] Live-strip chips have no depth of meaning.**
Demo tile shows an unexplained "OFF" badge; "No activity in the last 3h" strip
overlays the tile; the live strip mixes rule fires, VLM status, and (see F1)
other installs' events with no labels a new user could parse.

## C. Navigation and IA

**C1 [P0] The Rules page has no navigation entry.**
`MegaNav.tsx` link inventory: Activity (Everything/Alerts/Incidents/Journeys/
Conversations/Recordings/Camera recaps), Ask (Ask Nurby/Memory/Scheduled
questions), People (People/Vehicles), top-level Home/Cameras/Settings. **Rules
appears nowhere.** The product's headline feature ("wire a rule that flashes a
siren") is reachable only via Settings → "Alert rules", the onboarding flow,
or typing `/rules`. Natural-language Search (`/search`) is likewise absent
from nav.

**C2 [P2] Settings hub promises 6 buckets, page contains 20+ sections.**
"Configure Nurby" jump cards list AI models / Cameras / Alert rules / Storage /
Notifications / Camera access. Scrolling reveals Telegram, MQTT, Invite keys,
Camera Voice, Privacy Blur, Nudity Blur, Objects to detect, Journey idle
window, Idle AI enrichment, FindAnything, Morning digest, updates, and more —
several not represented in the hub; "Alert rules" appears twice (hub card and
Alerts tab). Mixed save models (some toggles autosave, others need explicit
save) with no visible pattern.

**C3 [P2] System rules look like user rules.**
A fresh install shows "2 rules configured": "Camera content health" and
"Camera content health recovered", enabled, with Edit/⋯ menus, indistinguishable
from rules the user created (screenshot `07-rules.png`). Nothing marks them as
system-owned; toggling them off silently disables self-monitoring.

## D. Camera experience

**D1 [P1] The camera workspace has no live view.**
`/cameras/[id]` renders breadcrumb, info bar, activity strip, and
Settings/Activity tabs — no video anywhere (`frontend/src/app/cameras/[id]/
page.tsx` renders no `<video>`/WebRTC frame; screenshot `06-camera-workspace.png`).
Clicking a camera to "open the camera workspace" shows everything *about* the
camera except the camera. To watch it you must go back Home.

**D2 [P2] Status semantics contradict reality.**
The demo camera plays fine on the wall (direct `<video>` fallback) yet the
workspace header says "Offline". A brand-new user cannot reconcile "it's
playing but offline". Tile badge "OFF" (recording off) is unexplained.

**D3 [P3] Camera settings wall exposes deep knobs immediately.**
Recap model/prompt textareas, "Summarization ADVANCED", "Conversation Gap",
detection confidences — all in one scrolling form. "Quick setup" personas
(Front Door, Baby Cam, Pet Cam…) are excellent but sit at the top of a wall
that invites fiddling.

## E. Copy and content bugs

**E1 [P1] Rule plain-language preview renders a broken sentence.**
Rules page preview for the system rule: `Notify: "the camera camera health
degraded: [reason]". Cooldown, 60 minutes.` — duplicated word "camera camera"
and a raw `[reason]` placeholder shown to users (screenshot `07-rules.png`).

**E2 [P2] Developer numbers and jargon in user copy.**
"Min score 0.50" (Nudity Blur), "Journey idle window", "AI backlog",
"Everyone's questions", truncated sentence "Who outside the household can see
what", Ask composer shows "$0.00 today" + "pick a model" chip when no model
exists. (screenshots `08-settings-*.png`)

## F. Cross-instance event leak (observed live)

**F1 [P1] Dashboards share live alerts across installs.**
`WS_RELAY_CHANNEL = "nurby:ws:broadcast"` (`services/api/ws.py:106`) is a fixed
Redis pub/sub channel; Redis pub/sub ignores the database index, so every Nurby
stack pointing at the same Redis server (the default for dev stacks on one
host, and common when people run a QA stack beside prod) relays every
`event_fired`, VLM status, and notification to every other stack's dashboards.
Observed live twice during the review: a "Rule fired · Person at the door ·
Front door" chip appeared on the fresh install at 12:27:58 AM; neither the
fresh DB nor any local DB contains that rule or camera — it came from another
local stack's activity over the shared channel. Clicking the chip lands on
`/events` which correctly shows "No alerts match these filters" — a trust-
damaging moment ("my system fired an alert for a camera I don't have, and the
alerts page says nothing happened").

---

## What already works well (keep)

- Add-camera failure handling: "The camera did not respond: No response from
  … Fix it and try again, or submit again to add the camera anyway" + concrete
  checklist (powered on, same network, firewall). Best-in-flow copy.
- Model download cancel path: "Download cancelled. Resume anytime from
  Settings; finished layers are kept." + honest summary screen.
- "AI provider optional" banner; Ask page's no-provider state ("Set one up" /
  "Use keyword search →"); LocalAIHintCard with the one-line command + Copy.
- People empty state (explain → add with photo → go to cameras).
- Cameras page guidance ("Click a preview to open the camera workspace…").
- Quick-setup personas on the camera; content-health explainer.
- Provisional-owner start with adaptive "Your footage is live" secure-nudge.

---

## Remediation plan (sections are independently implementable)

**S1 — Restore the real first run (P0)**
Auto-open `OnboardingWizard` on a true first visit (admin, zero cameras, not
dismissed — localStorage + server flag). Order: Welcome (magic/manual) →
storage → camera → provider (optional) → done. Fold the SetupWizard goal flow
in as the optional "first alert" step at the end (or explicitly hand off to
it) so there is one wizard, not two. Update README to describe what actually
happens. Acceptance: fresh DB → wizard on first paint; ≤2 clicks from "Do it
all for me" to live footage; skip/ESC everywhere; after dismissal no modal
returns without explicit action.

**S2 — Smart, honest model download in magic (P1)**
`_recommend_model` prefers an already-installed vision-capable model before
pulling; show human size ("8.5 GB") and percent in the progress UI; on
`ollama_outdated` skip the family up front and say which model is being tried
instead ("This Ollama can't run Gemma 4 — trying Gemma 3 4B"); no frozen
messages >5 s. Acceptance: with a small model already present, magic performs
zero downloads; with an old Ollama the first attempt is a compatible model.

**S3 — Calm the dashboard (P1)**
Banner/nudge logic keyed to install state: 0 real cameras → neutral empty-state
messaging, no red "Not recording"; demo camera tile "OFF" badge gets a tooltip
("Recording is off for the demo camera"); one floating surface per corner via a
single nudge manager (secure-account nudge gets a layout slot, not an overlay);
hide "Try last 30 days" when install age < window; gate "Try asking Nurby"
chips on provider presence; render the "Connect your first camera" empty state
inside the wall itself when 0 cameras. Consolidate the three secure-account
surfaces into one.

**S4 — Navigation surfaces Rules and Search (P0)**
Add Rules to the primary nav (top-level or a labeled menu item) and Search
alongside; keep mega-menus for depth. Mark system rules ("System" badge,
collapsed group, excluded from the "N rules configured" count). Acceptance:
from any page, Rules is reachable in ≤1 click; system rules visually distinct
and labeled.

**S5 — Camera workspace shows the feed (P1)**
Live view (WebRTC/HLS; file cameras fall back to the direct `<video>` player
already built for the wall) at the top of `/cameras/[id]`, collapsible, with
the existing PTZ overlay; unify status semantics so a playing file camera is
not "Offline". Acceptance: clicking a tile in /cameras shows the live feed in
the workspace for every stream type the wall supports.

**S6 — Copy and preview fixes (P2)**
Fix "the camera camera health degraded: [reason]" preview rendering (token
substitution + no raw placeholders); rewrite system-rule action copy; replace
"Min score 0.50" with plain words; dedupe storage-step heading; collapse the
.env warning into an "Advanced" disclosure; hide "$0.00 today"/model chip when
no models; consistent sentence voice in Settings section descriptions.

**S7 — Settings IA pass (P2)**
Hub cards cover every section (audit the 20+ sections into the buckets, add
missing ones: safety, integrations, tuning); consistent save affordance per
section (explicit autosave badge or Save button, never mixed silently);
"Alert rules" not duplicated between hub and Alerts tab.

**S8 — Namespace the WS relay channel (P1, small)**
Derive the channel from the Redis DB index or an instance id
(`nurby:ws:broadcast:{db}`) and add a regression test with two APIs sharing one
Redis. Acceptance: two stacks on one Redis no longer see each other's events;
single-stack behavior unchanged.

## Deliberately not proposed

- Persona/place personalization, delivery provenance, workspace multi-site —
  covered by #204/#199/#193.
- Dark/light theme, i18n, mobile — out of scope for first-run.
- Changing the provisional-owner security model — documented tradeoff.

---

## Review outcomes (adversarial PM + EM pass, same day)

Both reviews verified every claim against source and reshaped the plan. The
final issue list below supersedes S1–S8 as originally written.

Key corrections accepted:

1. **S4 conflicts with a recorded decision.** `docs/ia-rollout.md` (2026-09-14,
   phase 3, all ticked) decided "Rules live under Settings › Alerts, with a
   shortcut from Home". Adding a top-level nav item would silently violate the
   source of truth. The real gap: the promised Home shortcut was never built.
   The issue implements the shortcut (and system-rule labelling), not a nav
   re-architecture.
2. **Don't merge the wizards.** SetupWizard is wired to the activation
   milestone backend (`/api/auth/me/activation`, draft-rule/configure); the
   launcher pill only retires when the milestone verifies. Merging risks the
   funnel and strands the badge. S1 ships auto-open + step reorder + an
   explicit hand-off to the goal flow only.
3. **The dismissal flags exist but are write-only.** `localStorage
   "nurby-onboarding-dismissed"` (`OnboardingWizard.tsx:55`) and server
   `onboarding_dismissed` (`system.py:636`) are never read by the dashboard.
   S1's core work is the read path plus a strict zero-camera gate so existing
   admins are never nagged.
4. **The Redis fix is a key-prefix strategy, not one channel, and cannot key
   off the DB index** (the observed leak had both stacks on DB 0). Affected:
   `nurby:ws:broadcast`, `nurby:heartbeat:*`, `nurby:health:*`,
   `nurby:camera_status`, `nurby:stream_restart:*`, `nurby:mqtt:out`. Fix =
   instance id (env/compose project) wired through `shared/redis_keys.py`,
   with one-release dual subscription for rolling deploys. S3's banner fix
   depends on this (cross-read heartbeats make health lie).
5. **"Not recording" gating must reuse the real-vs-demo camera logic**
   (`system.py:591`), not camera count alone: a demo-only install has no
   ingestion heartbeat, and ≥1 real camera must keep the banner.
6. **The wall player to reuse lives in `CameraSidebarCard.tsx`** (WebRTC
   iframe, remote-file `<video>`, token-authed `/preview`, webcam), not
   `CameraWall.tsx`. And "playing but Offline" is backend truth:
   `services/ingestion/stream.py` never marks file cameras live — fix at the
   source, not with a frontend override.
7. **`_unsupported_families` already exists** (`ollama_deploy.py:180/439`) but
   is only seeded after a failed pull; the magic issue needs a proactive
   version probe/seeding at recommend time. The installed-model list and a
   cheap `_model_installed` path already exist (`:601-646`).
8. **E1 ("the camera camera health degraded: [reason]") is a regression** of
   the July F30/F48 fix; the template lives at `services/api/routes/rules.py:57`
   and `services/events/engine.py:402`. Fix = shared substitution helper +
   regression test.
9. **Settings hub audit cut.** `docs/settings-layers.md` already defines the
   IA contract ("household or Advanced"); the issue applies that contract to
   the current page (e.g. "Journey idle window" and "Idle AI enrichment" are
   documented Advanced but render as first-class) instead of inventing a
   bigger hub.
10. **Add instrumentation** to the wizard issue: `wizard_shown` /
    `magic_clicked` funnel into the existing `/api/auth/onboarding/metrics`
    and `seconds_to_first_useful` (`shared/activation.py:163`).
11. **Timezone:** wizard should infer and confirm timezone (compose defaults
    services to `TZ:-UTC`; recaps fire at wrong local hours otherwise).
12. **README honesty:** fold the web first-run description check and the
    mobile-mockup honesty note (README presents a "More" tab IA that
    ia-rollout phase 2 removed) into the first-run issue.

### Final issue list

| # | Priority | Issue |
|---|----------|-------|
| [#291](https://github.com/Eshpelin/nurby/issues/291) | P0 | Namespace shared Redis keys/channels per instance (cross-install event/health leak) |
| [#293](https://github.com/Eshpelin/nurby/issues/293) | P0 | Restore the guided first run (auto-open, reorder, read dismissal flags, instrument) |
| [#317](https://github.com/Eshpelin/nurby/issues/317) | P0 | Make Rules reachable (documented Home shortcut) + distinguish system rules |
| [#304](https://github.com/Eshpelin/nurby/issues/304) | P1 | Magic: recommend installed models first, probe Ollama version, honest download progress |
| [#318](https://github.com/Eshpelin/nurby/issues/318) | P1 | Calm the dashboard: state-true warnings, no floating overlaps, contextual empty states |
| [#319](https://github.com/Eshpelin/nurby/issues/319) | P1 | Camera workspace: show the feed (reuse the sidebar-card player stack) |
| [#320](https://github.com/Eshpelin/nurby/issues/320) | P2 | Copy and preview correctness pass (rule-preview regression, jargon, placeholders) |
| [#321](https://github.com/Eshpelin/nurby/issues/321) | P2 | Settings page: apply the settings-layers contract |

Build order (EM): 1 → 5; 2, 3, 4 independent; 6 after 1 (status truth); 7, 8
anytime. All eight are independently shippable.
