# Frigate Docs Parity Study

**Date:** 2026-07-28. **Author:** automated review.

A net-new study, independent of `docs/frigate-study/` (which mined Frigate's merged PRs).
This one goes straight at Frigate's **official documentation** and asks a single question:

> Feature by feature, as Frigate *documents* it to users, what does Nurby have, partly have,
> or lack? And which Frigate docs are worth mirroring one-to-one?

## Method

1. Pulled every feature-relevant markdown file from `blakeblackshear/frigate` `docs/docs/`
   (`configuration/`, `usage/`, `integrations/`, `frigate/`) at branch `dev`. 61 files.
2. Extracted the full heading skeleton (every documented feature/sub-feature).
3. For each, checked Nurby's actual state by grepping `services/` + `shared/` (evidence, not
   assumption) and cross-referencing the codebase.
4. Classified: **HAVE** (parity or ahead) / **PARTIAL** / **MISSING** / **N/A** (excluded by
   Nurby's architecture, deliberately not chased).

## Files

- `findings.md` - the full feature-parity matrix + prioritized implementation plan.
- `docs-index.md` - the Frigate doc list and which Nurby subsystem owns each.

## One-line answer

Nurby is at or ahead of Frigate on the AI surface (VLM, agent, face, LPR, audio+STT, semantic
search, journeys, guardian). The real gaps are all in the **NVR/operator plumbing** Frigate has
polished over years: motion search/review, per-user camera access, recording retention modes,
home/away profiles, semantic-search triggers, and the home-automation integrations (MQTT / Home
Assistant / HomeKit / Prometheus). See `findings.md` for the ranked list.
