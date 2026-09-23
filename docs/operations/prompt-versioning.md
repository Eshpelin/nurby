# Versioned VLM prompts

**Issue:** #218 · **Status:** shipped. Pairs with #214 (golden scorecards cite a prompt version).

## Why

To claim "prompt v2 improved caption faithfulness" you must know which prompt
produced which caption, and be sure the version moved when the prompt did.
`ObservationVlmPass.prompt_version` already stored a version, but it was
hardcoded `"v1"`, so it meant nothing.

## What shipped

- `services/perception/prompt_registry.py` pins, per lens, the current
  `version` and the `sha` of the prompt text that version corresponds to
  (lenses: `attributes`, `temporal`, `anomaly`, `summary`, plus `verify` /
  `repair`).
- The enrichment worker now stamps `version_for(lens)` on every
  `ObservationVlmPass` it writes, instead of a literal `"v1"`. A pass whose
  lens is not registered (e.g. the live first-pass caption produced elsewhere)
  is recorded as `v0-unregistered`, which is honest rather than a false `v1`.
- A drift test (`tests/test_prompt_registry.py`) fails if a registered
  prompt's text changes without its `sha` being updated and its `version`
  bumped, and if any pass-producing lens is missing from the registry. So a
  prompt edit cannot ship silently unversioned.

## Bumping a prompt

1. Edit the prompt text in `vlm_enrichment_worker.LENS_PROMPTS` (or
   `VERIFY_PROMPT` / `REPAIR_PROMPT`).
2. The drift test fails and prints the new `sha`.
3. In `prompt_registry.REGISTRY`, bump that lens's `version` (e.g. `v1` → `v2`)
   and paste the new `sha`.

New passes then record the new version, and a golden-set scorecard (#214) run
with `--prompt-version v2` is attributable to exactly that text.

Source: `services/perception/prompt_registry.py`,
`services/perception/vlm_enrichment_worker.py`, `tests/test_prompt_registry.py`.
