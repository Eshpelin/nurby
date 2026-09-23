# Golden-set evaluation (real footage)

**Issue:** #214 · **Status:** harness + scoring + intake shipped; footage collection is ongoing.

## Why this exists

The mocked agent-eval suite (`docs/agent-eval.md`) is a fast regression gate
that passes 30/30 against scripted fixtures at $0.00. It is **not an accuracy
claim**, the 16 September review says so explicitly. Real VLM behavior varies
wildly across night/IR, rain, low angles, and ambiguous identity. Without a
real-footage yardstick we cannot safely change a default model, tune a
prompt, or back the answer-contract claims of #198 and the tuning
suggestions of #196.

The golden set is that yardstick: labeled real footage that a
provider/model/prompt version is scored against, producing an **attributable
scorecard**.

> **Rule:** an accuracy claim cites a golden-set scorecard (provider, model,
> prompt version, judge), never the mocked run.

## Layout

```
services/agent/eval/golden/
    schema.py     # GoldenCase, MediaRef, GroundTruth, scenario families, load/save
    scoring.py    # deterministic checks + Judge protocol (KeywordJudge, LLMJudge)
    harness.py    # run_scorecard -> ScoreCard (markdown/json, per-family, coverage)
    intake.py     # turn #195 "incorrect" alerts into draft cases
scripts/golden_eval.py             # CLI: score / validate / intake
tests/agent_fixtures/golden/*.json # labels only. FOOTAGE IS NEVER COMMITTED
tests/test_golden_eval.py          # harness unit tests (deterministic, offline)
```

## Footage stays out of git

A case stores a `media` reference: a `sha256` (pins the exact bytes) and an
optional local `path`. The pixels live outside the repo. Two run modes:

- **CI / offline:** a case carries `recorded_output` (a previously captured
  model output). Scoring runs deterministically with no footage and no live
  model, using the `KeywordJudge`. This is the CI-friendly subset path.
- **Local, footage-backed:** pass a `runner(case) -> str` into
  `run_scorecard` that captions the real frame / answers the real question
  with the model under test, and use `LLMJudge` with a pinned judge model.

## Scenario families

The set must cover every family with a minimum count (see
`SCENARIO_FAMILIES` in `schema.py`), including true **no-event** cases (the
false-alert rate matters most):

`delivery`, `known_face`, `ambiguous_face`, `no_event`, `night_ir`,
`rain_obscured`, `missing_recording`.

`golden_eval.py validate` reports any family short of its minimum;
`score --require-coverage` exits non-zero on gaps so CI can gate a claim on a
complete set.

## Scoring

Every case gets three signals:

1. **Event presence/absence** against the closed-vocabulary `event_present`
   label. Deterministic, no model.
2. **Vocab gates**: `must_include` present and `must_not_include` absent.
   Deterministic. (E.g. a delivery caption must not say "stole".)
3. **Judge score** [0, 1] for open-ended faithfulness/correctness. The judge
   is pluggable and its identity is recorded on the scorecard:
   - `KeywordJudge` (default): token-overlap, deterministic, offline. Its
     pass bar is low because paraphrase overlap is naturally low. Use it for
     regression and CI, not for a headline accuracy number.
   - `LLMJudge`: a **fixed** judge model (never the model under test). The
     call is injected, so wire it to a pinned provider/model for a real run.

A case passes when presence is right, no vocab gate tripped, and the judge
score clears that judge's own threshold.

## Commands

```bash
# Score the recorded outputs already in the set (deterministic, offline):
python3 scripts/golden_eval.py score \
    --provider gemini --model gemini-2.0-flash --prompt-version v3

# Same, as JSON, written to a file, failing if coverage is incomplete:
python3 scripts/golden_eval.py score --provider gemini --model flash \
    --prompt-version v3 --json --out scorecard.json --require-coverage

# Check scenario-family coverage:
python3 scripts/golden_eval.py validate

# Grow the set from users' "incorrect" alert reviews (#195):
python3 scripts/golden_eval.py intake
```

A scorecard names the provider, model, prompt version, judge, and generation
time, then reports event accuracy, caption faithfulness, Ask answer
correctness, overall pass rate, per-family breakdown, coverage gaps, and the
list of failing cases.

## Growing from real failures (#195 -> #214)

When a user marks an alert `incorrect`, `golden_eval.py intake` writes a
draft case (`feedback-<event_id>.json`, `source: feedback:<event_id>`)
carrying the footage reference and what the model said. It is idempotent (a
re-run never clobbers a curator's edits). A human then fills
`truth.reference` with the correct description. No manual schema work, and no
duplicate cases.

## Deferred / follow-ups

- Wiring `LLMJudge`'s `ask` to a specific pinned provider/model in the CLI
  (kept injectable here so it stays testable and provider-agnostic).
- Sequencing scorecards with prompt versioning (#218) so a card reads
  "prompt v3, gemini-2.0-flash: 91% caption faithfulness".
- Bulk footage collection to hit the per-family minimums; the shipped
  `ex-*` cases are format templates with placeholder hashes.
