# Versioned VLM prompts

**Issue:** #218 · **Status:** shipped. Pairs with #214 (golden scorecards cite a prompt version).

## Why

To claim "prompt v2 improved caption faithfulness" you must know which prompt
produced which caption, and be sure the version moved when the prompt did.
When a user reports a bad caption or a wrong alert, the first question is
"which prompt wrote this?", and the answer has to be exact.

## The registry

`services/perception/prompt_registry.py` holds every production VLM prompt
under a stable key:

| Key | Used by | Live text |
| --- | --- | --- |
| `live_caption` | first-pass scene caption (`vlm_queue`) | `vlm.SYSTEM_PROMPT` |
| `attributes`, `temporal`, `anomaly`, `summary` | idle enrichment lenses | `vlm_enrichment_worker.LENS_PROMPTS` |
| `verify`, `repair` | summary verification and repair | `VERIFY_PROMPT` / `REPAIR_PROMPT` |
| `action_classify` | per-person action labels | `actions.CLASSIFY_SYSTEM_PROMPT` |
| `agent_analyzer` | agent `analyze_frame` / recording analysis | `analyzer.ANALYZER_SYSTEM_PROMPT` |

- `REGISTRY` pins each key's shipped default `version` and the `sha` of its
  text. `tests/test_prompt_registry.py` fails if a live text changes without
  its sha and version moving, or if a prompt is not registered.
- `EXTRA_VERSIONS` holds other immutable versions of a key: retired texts
  (for rollback, and so old rows still show their exact prompt) and
  candidates awaiting promotion.
- The `prompt_versions` app setting (`{key: version}`) chooses the active
  version. Call sites resolve it at call time (cached for 30 seconds per
  process), so a promotion reaches every worker within that window.

## What gets stamped

| Output | Where the stamp lives |
| --- | --- |
| Enrichment pass | `observation_vlm_passes.prompt_key / prompt_version / prompt_text` |
| Live caption | `observations.caption_prompt_key / caption_prompt_version` (+ `caption_prompt_text` for a camera's custom prompt) |
| Action label | `observation_actions.prompt_key / prompt_version` |
| Agent VLM answer | `prompt_key` / `prompt_version` in the answer JSON (`agent_vlm_calls.response`, `vlm_frame_analysis.response_json`) |

Summary passes also record `verify_prompt_version` and, when a repair ran,
`repair_prompt_version` inside `attributes.verify`.

A camera with its own VLM prompt is stamped `live_caption/custom` with
version `c-<sha>`, and its text is stored on the observation because the
registry does not hold it.

Rows written before stamping are reported as `legacy/unknown` with no text.
Nothing is backfilled with a guess.

The agent analyzer cache is scoped by prompt version, so promoting or rolling
back never serves an answer a different prompt wrote.

## Debugging a caption

- UI: open a moment and expand **Prompts used**. It lists the live caption,
  each enrichment pass and each action label with its key, version and
  exact text.
- API: `GET /api/observations/{id}/prompt-provenance`.

## Changing a prompt

1. Copy the current text into `EXTRA_VERSIONS[key]["v1"]` (it is still the
   text behind every existing `v1` row).
2. Edit the live constant. The drift test fails and prints the new sha.
3. Bump `REGISTRY[key]` to `v2` with the new sha.

To ship a candidate without making it the default, add it to
`EXTRA_VERSIONS[key]["v2"]` instead and leave the live constant alone.

## Scoring a candidate against the golden set

```
python3 scripts/golden_eval.py score --provider P --model M \
    --prompt-key live_caption --prompt-version v1 --json --out base.json
python3 scripts/golden_eval.py score --provider P --model M \
    --prompt-key live_caption --prompt-version v2 --json --out cand.json
python3 scripts/golden_eval.py compare base.json cand.json
```

`--prompt-key` pins the text sha into the scorecard. For offline runs a
golden case can carry `recorded_outputs: {"v1": ..., "v2": ...}`. `compare`
prints metric deltas plus newly failing and newly passing cases, and exits 1
when any metric drops (beyond `--tolerance`) or any case that passed now
fails.

## Promotion and rollback

A data change, not a code change:

```
GET  /api/prompts                          # keys, versions, active version
GET  /api/prompts/{key}/versions/{version} # exact text + sha
PUT  /api/prompts/{key}/active {"version": "v2"}   # admin only
```

Only versions the registry holds can be activated. Choosing the shipped
default clears the override. An unknown version left in the setting is
ignored and the default is used.

Source: `services/perception/prompt_registry.py`,
`services/api/routes/prompts.py`, `services/api/routes/observations.py`,
`services/agent/eval/golden/harness.py`, `tests/test_prompt_registry.py`.
