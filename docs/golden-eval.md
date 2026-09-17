# Golden-set evaluation harness (VLM captions and Ask answers)

Issue #214. A reproducible harness that scores two user-facing outputs
against labeled ground truth on real footage.

- **Caption faithfulness.** Does the VLM's structured caption describe
  what actually happened, and does it agree on whether an event is
  present?
- **Ask answer correctness.** Does the agent's answer to a labeled
  question match the known answer?

This is the real-footage yardstick that complements the mocked agent
eval (`services/agent/eval`, `.eval-report.md`). The mocked suite is a
fast structural gate and passes at $0.00; it is explicitly not an
accuracy claim. Accuracy claims cite a **golden scorecard** produced
here, never the mocked run.

## Why it runs in CI without a model

Footage is never committed (consistent with the analytics stance in
#199). Each fixture stores the **label** plus a committed
`mock_prediction` block. The default providers are *replay* providers
that return that block, so `python -m services.agent.eval.golden.cli`
and the pytest suite run deterministically with no live model, no key,
and no network. This proves the harness and scoring wiring. It is not a
real-footage accuracy number.

## Run it

Replay (deterministic, what CI runs):

```
.venv-test/bin/python -m services.agent.eval.golden.cli \
    --provider replay --model mock --prompt-version v0 --out golden-scorecard.md
```

The pytest gate lives in `tests/test_golden_eval.py`:

```
.venv-test/bin/python -m pytest tests/test_golden_eval.py -q
```

## Fixture format

Small JSON files under `services/agent/eval/golden/fixtures/`
(`captions/` and `ask/`). One case per file:

```json
{
  "id": "cap_delivery_day",
  "kind": "caption",                 // "caption" | "ask"
  "scenario": "delivery",            // one of the scenario families below
  "footage": {                        // pins the clip; footage NOT in git
    "hash": "sha256:...",
    "source": "sample:driveway_day_package.mp4"
  },
  "input": {"camera": "front_door", "window_seconds": 8},
  "ground_truth": {
    "event_present": true,
    "must_include": ["package"],     // required phrases (deterministic gate)
    "forbidden": ["intruder"],       // confident-wrong phrases to catch
    "reference": "A driver leaves a package at the door."  // semantic-lite only
  },
  "mock_prediction": {                // replayed in CI; ignored by a live run
    "caption": "A courier places a cardboard package by the front door.",
    "event_present": true
  }
}
```

`ask` cases carry the question under `input.question` (or `prompt`) and
put the answer keywords in `must_include`.

## Scoring

Three transparent, model-free metrics (`scoring.py`):

- **exact_match** — normalized string equality (rarely used).
- **keyword_coverage** — fraction of `must_include` phrases present.
  This is the primary pass gate for closed vocabularies (object class,
  known person, event wording). Case- and punctuation-insensitive,
  supports multi-word phrases.
- **semantic_lite** — token-set Jaccard overlap against `reference`.
  Reported only; a cheap stand-in for the LLM-as-judge score a live run
  would add. Never a hard gate (too easy to game).

A case **passes** when keyword coverage is 1.0, no forbidden phrase
leaked, and predicted event presence matches the label.

## Scenario families

The set must cover, with true "no event" cases included:

`delivery`, `known_face`, `ambiguous_face`, `no_event`, `night_ir`,
`rain_obscured`, `missing_recording`.

The scorecard lists a **Coverage gaps** section for any family missing
from a run. The v1 committed set has at least one case per family (12
cases total); a fuller set targets 100–200 with minimum counts per
family (a healthy start: ~20 each, weighted toward `ambiguous_face`,
`night_ir`, and `rain_obscured`, plus a solid block of true `no_event`
and `missing_recording` negatives).

## Running against a real provider

Supply your own provider to `run_golden_set` in code; the CLI wires the
replay providers only. The seam is `services/agent/eval/golden/providers.py`:

- `CaptionProvider.caption(case) -> CaptionPrediction`
- `AnswerProvider.answer(case) -> AnswerPrediction`

`LiveVLMCaptionProvider` sketches the one clean seam into the production
`services.agent.analyzer.call_vlm_structured`. Because footage is not in
git, you pass a `frame_loader(case) -> list[np.ndarray]` that resolves
the pinned footage on your machine. Stamp the run with a `RunConfig`
(`provider`, `model`, `prompt_version`, `mode="live"`) so the scorecard
is attributable, e.g. "prompt v3, gemini-2.0-flash: 91% caption
faithfulness". Add `--min-pass-rate` to gate a live run.

## Growing the set from real failures (#195 intake)

Incorrect reviewed alerts feed the golden set with no manual schema
work. `intake.alert_to_golden_case(observation, feedback)` takes an
observation row and its `EventFeedbackCreate` feedback
(`rating="incorrect"`, `reason` in `wrong_object` / `wrong_person` /
`duplicate` / `timing`) and emits a golden case:

- `wrong_object` / `wrong_person` — the mis-asserted caption becomes a
  `forbidden` phrase; the event is treated as absent unless the
  reviewer supplies a `correct_label`.
- `duplicate` / `timing` — a real event mis-fired or mis-timed; event
  stays present, corrected wording seeds `must_include`.

Write the returned dict to a new fixture JSON and it loads through the
same path as a hand-authored case.

## What a fuller slice would add

- 100–200 labeled clips with real footage hashes stored out of git
  (object store / local cache keyed by hash).
- CI wiring: run the replay gate on every PR; schedule opt-in live
  runs that post a scorecard and diff it against the last prompt/model.
- Prompt-versioning integration (#196/#198) so scorecards are keyed by
  prompt version automatically.
- An LLM-as-judge scorer with a fixed judge model for open-ended
  caption faithfulness, alongside the deterministic keyword gates.
