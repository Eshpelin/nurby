# FindAnything (Visual Grounding) — Design & Implementation Plan

Status: **Draft for review** (pre-implementation). Owner: TBD. Last updated: 2026-06-19.

This document plans the integration of an open-vocabulary visual-grounding model
(reference model: NVIDIA **LocateAnything-3B**) into Nurby, exposed in two places:

1. **Search** — let a user ask Nurby to locate a specific thing in a feed/recording
   and get back frames with boxes drawn on *where* it is.
2. **Rules** — let a user author a deterministic automation condition such as
   "when a `chicken` is located in the coop, do X".

It has been through one Senior-Engineer review and one Product-Manager review
(see the Review Log at the end). Several v1 assumptions were wrong; this is the
corrected plan.

---

## 1. The reference model (facts)

LocateAnything-3B (`nvidia/LocateAnything-3B`):

- **Task:** open-vocabulary visual grounding — referring-expression localization,
  multi-object detection, GUI/text/document grounding. We use only the natural-scene
  object/attribute/referring-expression part.
- **Input:** RGB image + natural-language text prompt (object category, referring
  expression). Up to ~2.5K resolution.
- **Output:** structured **text** with coordinate tokens: `<box> x1, y1, x2, y2 </box>`
  and points `<box> x, y </box>`, coordinates as **normalized integers in [0, 1000]**.
  Multiple boxes per response are possible.
- **Architecture:** MoonViT vision encoder + Qwen2.5-3B-Instruct LM + MLP projector,
  Parallel Box Decoding. 3B params.
- **Inference:** `transformers==4.57.1` (PINNED — 5.x breaks the model's custom modeling
  code) with `trust_remote_code=True`, BF16. A datacenter NVIDIA GPU is *recommended* for
  throughput, but **not required**: it also runs on **Apple Silicon (MPS)** and CPU. Validated
  on an M4 / 48 GB MacBook Pro — 15 s load, ~1–5 s/frame in `slow` (autoregressive) mode.
  The default `magi` attention is CUDA-only; off-CUDA we force `sdpa` (fully supported), and
  `fast`/`hybrid` Parallel-Box-Decoding modes need CUDA kernels so off-CUDA clamps to `slow`.
  Modes fast/slow/hybrid.
- **License:** **NVIDIA non-commercial** (academic/non-profit research; fine for personal /
  self-hosted use). The repo is **NOT gated** — it downloads with no HF token and no license
  click-through. The architecture stays model-agnostic so a permissively-licensed grounder
  (Grounding DINO / OWLv2 / extended YOLO-World) can drop in for a commercial path if needed.

### 1.1 Two properties that drive the whole design

- **The output has no calibrated confidence.** It is an autoregressive text decoder, not
  a detector with a softmax. Any "confidence" is a heuristic (e.g. token logprob) and is
  not comparable across prompts/images. **We do not rank by a fake confidence score.**
- **Referring-expression grounders hallucinate boxes.** They assume the referent exists
  and will emit a box for "the red backpack" whether or not one is present. This is the
  central correctness problem and is why **autonomous rule firing on a raw grounding box
  is forbidden** without a verification gate (see §6).

---

## 2. How it slots into the existing architecture

Nurby already has the right shapes; FindAnything reuses them rather than inventing new ones.

- **Ask agent (`services/agent/driver.py`)** is already a tool-using LLM loop with a
  deliberate cost ladder: cheap indexed tools (`query_observations`, `get_last_sightings`,
  `summarize_activity`) run first; expensive VLM tools (`analyze_clip`, `analyze_frame`)
  are gated behind a system-prompt "these are expensive, use only when needed" instruction
  plus per-user budget enforcement. **FindAnything is a new tool on this exact ladder.**
- **Rules engine (`services/events/engine.py` + `services/events/actions.py`)** already has
  the expensive-confirm pattern: a cheap trigger fires, then a `vlm_call` / `verify` action
  runs an expensive model and the chain branches on the result. **FindAnything-as-condition
  fits this mold.**
- **VLM provider/queue (`services/perception/vlm.py`, `vlm_queue.py`)** is good prior art for
  an HTTP-fronted model behind a bounded queue. We borrow the seam, not the per-camera
  concurrency model (grounding is per-GPU, not per-camera; see §5).

### 2.1 Single HTTP seam (key decision)

The model runs behind **one** interface: an HTTP `grounding` microservice. The service may
front a local in-process model *or* proxy a remote box, but Nurby's code only ever speaks
HTTP to it. This:

- collapses the testability problem (one fakeable seam, identical to the VLM HTTP seam);
- removes the `Provider`-table collision (grounding is its own service URL in config, **not**
  a `Provider` row — see §3.1);
- makes "local GPU" vs "remote endpoint" a deployment choice, not two code paths.

```
Search (/ask tool)  ─┐
                     ├─► GroundingClient (HTTP) ─► grounding service ─► model (local GPU or remote)
Rules (condition)   ─┘            │
                                  └─ parser + rescale + global GPU semaphore + caching
```

---

## 3. Product decisions (the experience)

### 3.1 FindAnything vs Ask — keep them distinct

| | Ask / Q&A (exists) | FindAnything (new) |
|---|---|---|
| Input | Natural-language question | Text description of a thing |
| Output | A sentence | Boxes on frames |
| Answers | what / who / when / how many | **where / show me / is it still there** |
| Grounded in | the pre-indexed log | the **raw pixels**, open-vocabulary |

One-liner: **Ask tells you a story about the past; FindAnything points at a thing in the
frame.** Do not market FindAnything as "better search" — it competes with the free, instant
index and loses. Market it as: *"YOLO knows 80 things. Your home has 8,000. Describe any of
them and Nurby points at it."*

### 3.2 The escalation UX (build this first)

One search box. Cheap indexed search runs free and instant. The deep GPU scan is never run
automatically; the user opts into it through **two entry points that feed one flow:**

1. **"Not seeing it? Scan the raw footage →"** at the bottom of *every* search result set
   (primary). This catches both zero-result queries **and** "results, but not the thing I meant."
   It frames the multi-second scan as a deliberate deeper search the user chose, so the wait feels
   earned, and it surfaces the capability exactly when it's relevant (discovery + latency
   justification in one).
2. **An optional "Deep visual scan" toggle** in the search bar (power users who already know they
   want the deep search and want to skip the cheap tier). Guardrails: **per-search and non-sticky**
   (resets each query, so nobody leaves it on and hammers the GPU), and labelled with cost
   ("slower, scans raw footage, uses GPU").

Both paths run the **same** flow: cheap index pre-filter to pick candidate frames (§3.3) →
grounding only on those → results stream back as **frames with boxes**. The only difference is
*when* the user signals intent (after seeing cheap results vs before). **Intent-routing still wins
in both** — a person/identity query routes to face-rec (§3.4) even in deep mode; the toggle must
not send "find Leo" to a model that has no concept of identity.

Empty results must say *what* was scanned ("Checked 1,240 frames across Front Door + Driveway,
last 24h. No ladder.") so a "no" is trustworthy. Boxes carry a dismiss/thumbs-down affordance
(feeds correction; see §6). Naming: the toggle is **"Deep visual scan,"** not "FindAnything"
(which over-promises — it can't find "Leo"). The cost-consent for the GPU run is handled by the
§3.6 mechanism.

### 3.3 Scope the scan with the index (the moat)

Never brute-force frames. Pre-filter candidate frames using cheap indexed signals before the
GPU sees anything: motion segments, observations that already carry relevant detections, and
camera role (entry/garage/yard via existing camera layout). Then **persist what FindAnything
locates back into the index as tags**, so the next search for that term is instant and free —
FindAnything teaches the index new vocabulary on demand, locally.

### 3.4 Person search — route by intent, do not merge

**FindAnything does open-vocabulary text grounding, not photo-based identity.** It cannot find
"Leo"; it can find "a child in a red jacket." Identity is already solved by InsightFace +
body re-id (indexed, exposed via journeys/last-sightings). Routing:

- "find this **person**" (named/known) → face-rec / re-id.
- "find this **thing**" → FindAnything.
- uploaded **photo of a person** → re-id (match against known People/clusters).
- "a person in a blue coat" (un-enrolled, described) → FindAnything.

"Search by uploaded image of a person" is a legitimate feature but belongs to the **face
stack** as a **sibling workstream** (§8), *not* to LocateAnything. Detect intent at input and
say which door was taken ("Leo is a known person — showing his sightings"). Two labeled doors
beat one magic door that lies half the time.

### 3.5 Tool vs baked-in — split by surface

- **Search (`/ask`):** a tool the agent may invoke, **but the expensive run is user-consented.**
  Agent proposes; user confirms the scan. No autonomous GPU burn inside a turn the user thinks is
  free. **This consent step is net-new infra — see §3.6. It is NOT the `analyze_clip` gate**
  (that gate is a server-side budget/camera-access check inside the tool function, not a user
  prompt).
- **Rules:** an LLM must **never** decide when a security automation fires. FindAnything runs as a
  **user-authored, deterministic, post-trigger `verify`-style action** (not a live trigger
  predicate — see §3.7 for why): a cheap trigger fires first, then grounding runs and the action
  chain branches on the result, logged and repeatable.

### 3.6 Consent is a user-initiated button, not agent pause/resume (simplified)

There are **two distinct consents**, do not conflate them:
- **License consent** (one-time, install) — accepting NVIDIA's terms. Folded into the Nurby
  install/enable flow (§4).
- **Cost consent** (per scan) — "this scan takes ~30s and uses the GPU, go?" This section is about
  that one.

An earlier draft proposed an agent-driven escalation (the LLM proposes a scan mid-turn, the turn
pauses for a confirm). That is hard: the `/ask` driver runs fire-and-forget, executes tools inline
and synchronously, and its WebSocket bus is **output-only** — **there is no way today to pause a
turn and resume on a user click**. Building that (inbound WS channel + pause/resume) was the
single biggest P1 risk.

**The §3.2 UI dissolves it.** Because the deep scan is launched by an explicit user action — the
"Scan the raw footage →" button or the "Deep visual scan" toggle — **the click itself is the cost
consent.** So the scan is a **direct user-initiated endpoint** (`POST /search/scan` → a job with
streamed box results), **not** an agent-loop escalation. No pause/resume, no inbound WS channel, no
`needs_consent` sentinel. This removes the hardest blocker from P1.

The Ask agent can still *mention* the option in its text answer and even render the same "Scan the
raw footage" button inline — but pressing it calls the same direct endpoint, so it stays
user-click-initiated and needs no new agent machinery. **True autonomous mid-turn agent escalation
(the LLM runs the GPU scan on its own inside a turn) is explicitly deferred** to a later phase; V1
never needs it.

### 3.7 Why a post-trigger action, not a live trigger predicate

The rules engine evaluates **live, synchronously, at observation-creation time** in the perception
pipeline (`services/perception/pipeline.py` calls `engine.evaluate(rule_data)`), off the
`rule_data` built from live YOLO/face detections. Grounding is an expensive async GPU call. You
**cannot** run it inside `evaluate()` without stalling the live ingestion path. So FindAnything in
Rules is a **post-trigger `verify`-style action**, not a new trigger type or a live condition: a
cheap trigger (motion / a coarse YOLO label) fires first, then the grounding action runs and the
chain branches on `{{vars.loc.*}}`. The engine already supports this exact shape
(`_execute_verify`, `vars` threading in `engine.py`). **No new trigger type is added in P3.** A
true autonomous grounding *trigger* (grounding deciding on its own that a rule fires) is the
deferred P4 item, and is exactly the LLM-decides-when-security-fires pattern we are avoiding.

### 3.8 Naming

"FindAnything" is fine as an internal codename but over-promises as a user verb (it can't find
Leo). Surface the action in context: **"Scan footage for…"** in search, **"Visual condition"**
in Rules. Avoid "AI Search" (collides with Ask). Honest tagline: *"Describe it, we'll point at it."*

---

## 4. Offline & installation (simpler than first assumed)

The v1 draft assumed this was a gated, token-required, must-mirror blocker. **That was wrong**
(verified by actually pulling the model): `nvidia/LocateAnything-3B` is a **public, ungated**
HuggingFace repo, so the weights download with **no HF token, no login, and no license
click-through**. So the first-time UX is genuinely one step:

1. User flips **Enable FindAnything** (off by default).
2. On first scan the grounding service runs `snapshot_download("nvidia/LocateAnything-3B")` —
   ~6 GB, no token — into its weights volume, surfacing progress on the health endpoint.
3. After that, run with `HF_HUB_OFFLINE=1` for a fully-offline runtime.

`GROUNDING_MIRROR_URL` remains an **optional** override only for air-gapped installs that cannot
reach huggingface.co. No token, mirror, or per-user license click is needed in the default path
(`scripts/setup-grounding.sh` is now just an optional pre-fetch).

**Not via Ollama.** Nurby already uses Ollama for the *general* VLM, but Ollama/llama.cpp serve
GGUF models from a fixed set of architectures and **cannot run LocateAnything** (custom
`locateanything` arch: MoonViT vision tower + Parallel Box Decoding + `trust_remote_code`, shipped
as safetensors + custom Python, no GGUF). So grounding is served by our own small transformers
service (the §2.1 HTTP seam), downloaded directly. The general VLM stays on Ollama, unchanged.

**Where it runs.** Datacenter NVIDIA GPU via the compose `grounding` profile is the throughput
path. **On Apple Silicon, run the service natively on the host** (`python -m
services.grounding.server`) — Docker Desktop cannot pass Metal/MPS into a Linux container — with
the API container pointing at it (`grounding_backend=remote`, `http://host.docker.internal:8800`).
Validated on an M4/48 GB: real model, ~15 s load, ~1–5 s/frame, 5 chickens located correctly.
CPU also works (slower). So it is **not** a GPU-gated feature; it is opt-in only because it is a
~6 GB download most self-hosters won't want by default.

Off by default. The base install never touches it. Grounding has a global enable flag
(default **off**) and a health surface (mirror the `vlm_health` navbar check) reporting
model-loaded / downloading / disabled.

**Remote backend = leaves the privacy boundary.** Sending frames (faces, plates, family) to a
remote endpoint is exactly what this product exists to prevent. It is a *knowing developer
escape hatch* for GPU-less V1 self-hosters: off by default, loudly labeled, **never** the V2
prosumer default. It is not co-equal with the local backend.

---

## 5. Cost, latency, concurrency (the GPU is one global resource)

The single GPU runs ~1 (maybe 2) grounding inferences at a time **across the whole system** —
not one per camera. The per-camera VLM-queue model does **not** transfer.

- **Global grounding semaphore**, not per-camera lanes.
- **Two priority lanes:** interactive search **preempts** background rules. A human is staring
  at a spinner; a rule is not.
- **Per-request frame budget + hard timeout** for the scan/"recent" path. `max_frames` is a
  real cost multiplier (N × seconds). Stream partial results as boxes appear.
- **Per-user rate limit** on the interactive endpoint (one user must not wedge the GPU for all).
- **Global rate limit + drop-oldest** for rule-driven grounding; plus the engine's existing
  cooldown / min_frames / fire-once dedup.
- Hard constraint to state in docs: roughly **N ≥ 3–4 cameras** with rule-driven grounding
  enabled will saturate one GPU and make interactive search unusable. Index pre-filtering (§3.3)
  is the primary mitigation.

Do not assume the VLM queue's pHash-dedupe / CLIP gate transfer — they answer "is this scene
worth captioning," a different question from "should I ground this prompt." A frame they drop
may be exactly the one a Locate query wants.

---

## 6. Correctness: hallucination, no-match, coordinates

- **No fake confidence.** Surface no score in V1, or label any heuristic rank explicitly as
  a heuristic. Do not treat it like a YOLO score.
- **Verification gate before any rule action fires.** A raw grounding box is not trustworthy
  enough to drive an alert. Require corroboration: co-occurrence with a cheap signal (motion /
  a coarse YOLO label in the same region) or a second-pass confirmation. The cheap pre-gate is
  about *cost*; this gate is about *correctness*. This is why **search ships before autonomous
  rules** — search keeps a human in the loop who can dismiss a wrong box.
- **Parser must handle:** boxes out of order (x2<x1), values <0 or >1000 (clamp), zero-area
  boxes, duplicate/multiple boxes, truncated `<box>` tokens when output hits the cap, empty
  output (= "not found"), and prose mixed with boxes. Cap parsed boxes and output tokens hard.
- **Rescale uses the exact dimensions of the image sent to the model**, not the original capture
  resolution. Getting this wrong puts every box in the wrong place (see §7 on clean frames).

---

## 7. Data model, frames, caching

- **The clean full-res frame is not retained today.** The pipeline persists only an
  **annotated** thumbnail (YOLO boxes burned in) via `_save_thumbnail()`, later overwritten by
  the VLM-queue's annotated copy. Grounding a burned-in thumbnail makes the model sometimes
  ground the *drawn box/text*, not the scene. So: **persist a clean, unannotated keyframe**
  (new storage + retention budget) — required *before* any retrospective/"recent" scan or cache.
- **`grounding_detections` JSON column on `Observation` is the wrong shape.** Grounding is
  query-dependent (prompt + frame → boxes); one observation can be grounded by many prompts.
  Use an **append-only table** keyed by `(observation_id, prompt_hash, model_revision)`, in the
  spirit of the existing `ObservationVlmPass` table.
- **Cache key** = `hash(model_revision, normalized_prompt, frame_content_hash)` — not just
  `observation_id`. This gives idempotency and avoids re-inference.

### 7.1 Write-back tags and rules are safe-by-default

`engine.evaluate()` only ever runs against **live `rule_data`** at observation-creation time; it is
**never** re-run when a tag is written to a stored `Observation`. So a retrospective scan that
writes FindAnything hits back as tags is **inert with respect to rules by default** — a retroactive
tag *cannot* trip a live `object_detected`-style rule without deliberately building a new
re-evaluation path. This means the safe option ("scan results don't fire automations") is what you
get for free, and the dangerous option (retroactive firing) is the one that would need new code and
an explicit decision. See §12-Q4.

---

## 8. Sibling workstream — "search by image" / find a known person

Out of LocateAnything scope but needed to answer "find a specific person from a photo." Build on
the existing face/re-id stack: embed the uploaded face (InsightFace), vector-search against
`FaceEmbedding` / known People/clusters, answer from journeys. Clearly labeled as a separate
door from FindAnything (§3.4). Tracked separately; not a dependency of V1 FindAnything.

---

## 9. Security

- **SSRF:** the remote grounding `base_url` is operator-supplied and fetched server-side. Today
  `vlm.py` posts to provider `base_url` with **no** netpolicy check (unlike webhooks/cameras).
  Route the remote grounding URL through `shared/netpolicy.py` (already written) — block
  link-local/internal targets (`169.254.169.254`, etc.).
- **Untrusted images:** the interactive endpoint accepts user-supplied frames/prompts. Guard
  against decompression bombs / pixel-flood / OOM on a 35 GB-VRAM model: size + dimension caps
  and a decode guard *before* the GPU.
- **Prompt injection:** the prompt is user-controlled. Blast radius is bounded (it emits boxes,
  not actions) but cap output tokens and parsed box count so a crafted prompt can't flood the
  parser/rule actions.
- **Resource exhaustion is the real security story:** per-user rate limit + the global semaphore
  (§5) prevent any logged-in user wedging the GPU.

---

## 10. Testability

CI has no GPU. Force everything through the HTTP seam (§2.1) so the only GPU-touching code is
the `server.py` model loader (smoke-tested behind a GPU marker, never in CI). Everything else is
pure and faked with a `GroundingClient` returning canned `<box>` strings:

- parser edge cases (§6);
- rescale-to-pixels against known dimensions;
- no-match / hallucination handling;
- global semaphore + interactive-priority fairness;
- rule-condition var plumbing (`{{vars.loc.*}}`).

---

## 11. Phasing (reordered from v1)

Ordering principle: ship the **human-in-the-loop, low-blast-radius** path first; defer anything
autonomous until the hallucination/verification story is proven.

- **P0 — Grounding core.** HTTP grounding microservice (`services/grounding/`), `GroundingClient`,
  `<box>` parser + rescale, global GPU semaphore + priority lanes, own config (not a `Provider`
  kind), global enable flag (default off) + health surface, fake client for CI. The opt-in
  `setup-grounding` gated-download flow (§4).
- **P1 — Search tool (interactive).** FindAnything as a tool on the `/ask` cost ladder with the
  user-consented "scan the footage?" escalation, live-frame grounding, boxes + dismissible UI,
  intent-split routing to face-rec for person queries (§3.4), index pre-filtering (§3.3). Low blast
  radius; validates real-world model accuracy. The deep scan is a **direct user-initiated endpoint**
  (`POST /search/scan`) launched by the §3.2 buttons — no agent pause/resume machinery needed
  (§3.6). The two UI entry points + the scan job + box-result rendering are the bulk of P1.
- **P2 — Clean-frame persistence + cache.** Persist unannotated keyframes (§7), append-only
  grounding-result table + cache key. Enables retrospective "scan last 24h" and the
  teach-the-index write-back.
- **P3 — Rules action (user-authored, gated).** A deterministic post-trigger `locate` action in
  the `verify`/`vlm_call` mold (§3.7 — **not** a new trigger type and **not** a live condition),
  with the §6 verification gate before any action fires. Never LLM-decided.
- **P4 — Deferred / cut from V1.** Autonomous `locate_object` trigger, timeline box overlay,
  heuristic confidence ranking. Revisit only after P1–P3 prove out.

### Cut from v1 scope
- Dual local+remote code paths → collapsed to one HTTP seam (remote is a deployment of the same
  seam, flagged as leaving the privacy boundary).
- `Provider kind="grounding"` → replaced by dedicated grounding config.
- Confidence ranking, timeline overlay, autonomous trigger → deferred (P4).

---

## 12. Open questions

1. **V1 backend (blocks P0/P1).** Ship the local GPU microservice as the reference, with remote as
   a labeled escape hatch? (Recommended.) Or remote-only for the first spike to defer GPU packaging?
1b. **Weights distribution (blocks P0).** Nurby-hosted mirror (one-click, needs legal OK on
   redistribution) vs automated HF token-pull (recommended default, zero legal exposure)? See §4.
2. **Retention for clean keyframes (blocks P2 schema).** How long do we keep unannotated frames for
   retrospective scans, given disk cost? Time-based, count-based, or "only frames a rule/scan
   touched"? Cannot write the P2 storage/eviction code without this.
3. **Commercial path (V2, not urgent).** When do we swap to a permissively-licensed grounder, and
   which one (Grounding DINO / OWLv2 / extended YOLO-World)? The seam supports it; only timing is open.
4. **Write-back tags (blocks P2 table shape + P3 safety).** Do FindAnything hits become first-class
   `Observation` tags or a separate "scan results" store? Per §7.1, retroactive rule-tripping is
   **impossible by default today** (rules only evaluate live `rule_data`), so the safe answer is
   free; choosing to make scan hits affect rules is an explicit new-code decision, not an accident.

---

## Review Log

- **v1 (skeleton)** — engineering-only phasing (P0 core → search → rule action → rule trigger →
  persistence). Assumed reuse of `fetch-models.sh`, a `Provider kind`, per-keyframe gating, a
  `grounding_detections` JSON column, and confidence ranking.
- **Senior-Engineer review** — found 2 blockers (gated/non-commercial weights vs the offline
  baked-image model; `Provider`-table active-selection collision) and major gaps (single-GPU
  global concurrency, no calibrated confidence + box hallucination, clean frame not retained,
  SSRF on `base_url`, GPU-less CI testing seam). Recommended one HTTP seam, dedicated grounding
  config, global semaphore + priority lanes, verification gate before rule firing, clean-frame
  persistence before retrospective scan, and reordering P4-persistence ahead of the "recent" mode.
- **Product-Manager review** — `/search` already redirects to `/timeline`; the real surface is the
  `/ask` agent cost-ladder, so FindAnything is a sixth tool, not a new mode. Keep Ask vs
  FindAnything distinct (story-of-the-past vs point-at-the-frame). Build the "scan the footage?"
  escalation first. Route person queries to face-rec, never to grounding. Search = agent tool with
  consent; Rules = user-authored deterministic condition, never LLM-decided. Persist hits back to
  teach the index.
- **Principal gate review (on this rewritten doc)** — verified the codebase claims are accurate.
  Found one must-fix the rewrite over-claimed: the "scan the footage?" consent step is **not** the
  `analyze_clip` gate and the `/ask` loop has **no mid-turn human-in-the-loop channel** today, so
  the consent flow is net-new (now specced in §3.6). Also flagged: P3 must be a post-trigger action
  not a live condition, and a new trigger type is not in scope (now §3.7); write-back→rules is
  safe-by-default because rules never re-evaluate stored observations (now §7.1); Q2/Q4 block P2/P3
  schema, not just P1 (now reflected in §12). Confirmed deferrals (P4) and "search before
  autonomous rules" ordering are correct. Verdict after fixes: **P0 is buildable now; P1 is gated
  on agreeing the §3.6 consent mechanism.**
- **Owner direction (folded in).** (1) Make the model download Ollama-grade and fold license
  consent into the Nurby install — done in §4, kept opt-in (not base-bundled) because most hosts
  have no GPU, with mirror-vs-token as the one open sub-decision. (2) Explained the two confusing
  items (offline-reconcile, Provider collision) — no doc change, both already reflected in §4/§2.1.
  (3) Two search entry points — a "Not seeing it? Scan the raw footage" button on every result set
  plus an optional non-sticky "Deep visual scan" toggle — adopted in §3.2. This also **dissolved the
  hardest P1 blocker**: the scan is now a direct user-initiated endpoint, so the agent pause/resume
  consent machinery is no longer needed (§3.6 rewritten).
- **Status:** three review passes + owner direction folded in.
- **Implemented** on branch `feat/findanything-locateanything` (owner decisions: local-GPU reference
  + remote escape hatch, Nurby mirror weights, personal/non-commercial use, auto-download in the
  search flow). Shipped P0 (grounding core: HTTP seam, `<box>` parser, priority gate, dedicated
  config, GPU service + mirror auto-download, docker-compose profile, SSRF), P1 (deep-scan endpoint
  + job poll + intent routing + two UI entry points + Settings card), P3 (`locate` rule action with
  the §6 corroboration gate), and P2's cache half (append-only `grounding_results` table + migration
  validated on a real pgvector Postgres + teach-the-index write-back). 63 unit tests green
  (46 new + 17 regression), ruff + tsc + eslint clean. **Deferred** (documented): persisting a clean
  unannotated keyframe in the live ingestion path (§7. unverifiable hot-path change. scan grounds
  the existing thumbnail meanwhile) and the autonomous P4 items. The real GPU inference in
  `services/grounding/server.py` is write-only behind a GPU marker per §10 (no datacenter GPU in
  CI), so the exact LocateAnything processor/generate call must be confirmed on real hardware.
