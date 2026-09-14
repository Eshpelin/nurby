# Five Places, Twelve Words: rollout checklist

The working plan for the information-architecture and vocabulary change
agreed on 2026-09-14. Proposal: the "Five Places, Twelve Words" artifact.
This file is the source of truth for progress; items are ticked as they
land in the working tree.

**Decisions taken**
- Guardian is a **mode**: a guardian signs into the same app and sees Home and Updates only.
- Rules live under **Settings › Alerts**, with a shortcut from Home.
- The stream is called **Activity**; `/timeline` redirects.
- Whole flow lands before review; nothing is committed by the agent.

## The five places

| Place | Question | Mobile tab | Web nav |
|---|---|---|---|
| Home | Is everything all right? | tab 1 | `/` |
| Cameras | Show me. | tab 2 | `/cameras` |
| Activity | What happened? | tab 3 | `/activity` (`/timeline` redirects) |
| Ask | Tell me. | tab 4 | `/ask` |
| People | Who is that? | tab 5 | `/people` |
| Settings | (gear) | app-bar action on Home | `/settings` |

## The glossary

| UI word | Replaces | Rule |
|---|---|---|
| Alert | Event (rule firing) | the only word for a rule firing |
| Updates | Event (guardian) | guardian-facing notifications |
| Recap | Digest, Summary (as nouns) | an AI narrative of a period: Morning recap, Camera recap |
| Sighting | Observation | what a camera saw, once |
| Blur area | Privacy zone | so Zone means motion zone only |
| Zone | Motion zone, guardian zone | unqualified; both are the same polygons |
| Scheduled question | Report | lives in Ask |
| Alert rule | Rule | when context is not obvious |
| Quick setup | Persona | already used on both clients |
| AI model | Provider | in every picker and settings label |
| Unknown person N | Cluster | never show cluster or an id |
| Incident, Journey, Conversation | (unchanged) | |

The API keeps its own names. This glossary is UI-only.

## Phase 1: words (both clients)

- [x] Mobile: every user-visible string audited against the glossary
- [x] Mobile: "Camera summaries" → "Camera recaps"; digests screen title and empty state
- [x] Mobile: "Events" → "Alerts" everywhere a person reads it
- [x] Mobile: "Reports" → "Scheduled questions"
- [x] Mobile: "Provider" → "AI model" in settings and the Ask picker
- [x] Mobile: privacy zone copy → "Blur areas"
- [x] Mobile: guardian "Alerts" card → "Updates" (guardian-facing) but household alerts stay "Alerts"
- [x] Web: MegaNav labels and descriptions ("Scheduled digests" → "Scheduled questions", etc.)
- [x] Web: page titles and section headings audited
- [x] Web: "Privacy zones" section → "Blur areas"
- [x] Web: "Observation" in user-facing copy → "Sighting"
- [x] Both: no user-visible string contains Digest, Event (as a rule firing), Persona, Provider, Cluster, Observation

## Phase 2: mobile IA

- [x] New Home screen: live conversation card, live cameras strip, unread alerts (badge on tab), morning recap, gear to Settings, "What should I be told about?" shortcut to Settings › Alerts
- [x] Tabs become Home · Cameras · Activity · Ask · People
- [x] Activity: the timeline screen with a search bar and filter chips: All, Sightings, Alerts, Incidents, Journeys, Conversations, Recordings, Camera recaps
- [x] Activity filters reuse the existing list screens' tiles and detail views
- [x] Ask gains a "Scheduled" tab holding the reports screen (an app-bar action, `/ask/scheduled`)
- [x] People gains a Vehicles segment (an app-bar entry, `/people/vehicles`; the lists stay whole)
- [x] Settings screen restructured into sections: Alerts (rules, notifications), Sharing (guardian household side, share links), Household, AI, Cameras, Integrations (webhooks, Telegram, API keys), Admin (camera access, AI backlog, everyone's questions), System
- [x] More screen removed; every old `/more/...` route still resolves (redirects) so nothing bookmarked breaks
- [x] Old tab "Alerts" folded into Home and Activity › Alerts
- [x] `flutter analyze` and `flutter test` green

## Phase 3: web IA

- [x] MegaNav replaced by the five places plus a Settings gear
- [x] `/activity` page: the timeline with search and the same filter chips; Incidents, Journeys, Conversations reachable from navigation for the first time
- [x] `/timeline` redirects to `/activity`; `/events` and `/recordings` keep their pages and carry the Activity filter bar
- [x] `/` (Home): recap, live, unread alerts, shortcut to Settings › Alerts
- [x] `/people` gains a Vehicles segment; `/vehicles` redirects
- [x] `/reports` reachable from the Ask panel as Scheduled questions; URL kept
- [x] `/rules` reachable from Settings › Alerts; `/rules` URL kept
- [x] `/pipeline` under Settings › Admin; URL kept
- [x] `tsc` and `npm run build` green

## Phase 4: settings layers

- [x] One decision per field: household layer or Advanced. Recorded in `docs/settings-layers.md`
- [x] Camera page (both clients): Advanced fold holding every tokens/seconds/threshold field (mobile folds per field; web folds per section, see settings-layers.md)
- [x] Settings (both clients): Advanced fold holding the raw system-settings editor
- [x] Nothing removed; every field still reachable

## Phase 5: guardian mode

- [x] Mobile: when `user.role == 'guardian'`, the shell shows Home (dependants) and Updates only
- [x] Web: same, replacing the MegaNav for guardian sessions (already in navbar.tsx; the household Guardian link moved to Settings > Sharing)
- [x] Household side of guardian lives under Settings › Sharing on both clients
- [x] A guardian never sees Cameras, Activity, Ask, People, Rules or Settings

## Verification before review

- [x] `flutter analyze lib test`; `flutter test`
- [x] `npx tsc --noEmit`; `npm run build`
- [x] Python suite still green (no backend change expected)
- [x] Every old route on both clients resolves to its new home
- [x] A grep for retired words in UI strings returns nothing
