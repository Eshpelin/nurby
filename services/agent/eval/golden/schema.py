"""Golden fixture data model + loader.

A golden fixture is a small JSON file. It carries the *label* (ground
truth) and a replayable ``mock_prediction`` so CI is deterministic. The
footage itself is never committed; ``footage.hash`` pins the clip a
label was authored against so a stale label is detectable.

Two kinds share one envelope.

- ``caption``. Scores a VLM structured caption for one clip.
- ``ask``. Scores an agent answer to one labeled question.

The envelope is deliberately flat so the #195 intake path can emit a
valid case without importing this module's dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Scenario families the golden set is required to cover (issue #214
# scope). The v1 committed set includes at least one case per family;
# the docs record the minimum counts a fuller set should reach.
SCENARIO_FAMILIES = (
    "delivery",
    "known_face",
    "ambiguous_face",
    "no_event",
    "night_ir",
    "rain_obscured",
    "missing_recording",
)

VALID_KINDS = ("caption", "ask")


@dataclass
class GroundTruth:
    """The labeled expectation for one case."""

    # Whether a real event is present in the clip/window. ``no_event``
    # and ``missing_recording`` families set this False; scoring checks
    # the prediction agrees.
    event_present: bool = True
    # Phrases the output must contain (case-insensitive substring). For
    # closed-vocabulary checks (object class, known person) this is the
    # deterministic gate.
    must_include: list[str] = field(default_factory=list)
    # Phrases the output must NOT contain. Catches confident wrong
    # answers ("intruder" on a delivery, a named stranger on an
    # unfamiliar face).
    forbidden: list[str] = field(default_factory=list)
    # Free-text reference used only for the semantic-lite overlap score.
    reference: str = ""


@dataclass
class GoldenCase:
    """One parsed golden fixture."""

    id: str
    kind: str
    scenario: str
    path: Path
    # The labeled question (ask) or the caption prompt/context note.
    prompt: str
    ground_truth: GroundTruth
    footage: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    # Committed replay prediction so the harness runs without a live
    # model. A live provider ignores this.
    mock_prediction: dict[str, Any] = field(default_factory=dict)
    # Provenance. "authored" for hand-labeled, "alert_intake" for cases
    # grown from #195 reviewed alerts.
    source: str = "authored"

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(
                f"golden case {self.id!r} has kind {self.kind!r}; "
                f"expected one of {VALID_KINDS}"
            )


def load_case(path: Path) -> GoldenCase:
    """Parse one JSON fixture into a ``GoldenCase``."""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return case_from_dict(data, path=Path(path))


def case_from_dict(data: dict[str, Any], *, path: Path | None = None) -> GoldenCase:
    """Build a ``GoldenCase`` from a plain dict.

    Shared by the file loader and the intake path so an alert-derived
    dict and a committed fixture take the exact same code route (this is
    what "no manual schema work" in the acceptance criteria means).
    """
    gt_raw = dict(data.get("ground_truth") or {})
    ground_truth = GroundTruth(
        event_present=bool(gt_raw.get("event_present", True)),
        must_include=list(gt_raw.get("must_include") or []),
        forbidden=list(gt_raw.get("forbidden") or []),
        reference=str(gt_raw.get("reference") or ""),
    )
    kind = data.get("kind") or "ask"
    prompt = data.get("prompt")
    if prompt is None:
        # ``ask`` fixtures usually carry the question under input.
        prompt = (data.get("input") or {}).get("question", "")
    return GoldenCase(
        id=data.get("id") or (path.stem if path else "unnamed"),
        kind=kind,
        scenario=data.get("scenario") or "untagged",
        path=path or Path(f"<memory:{data.get('id')}>"),
        prompt=str(prompt or ""),
        ground_truth=ground_truth,
        footage=dict(data.get("footage") or {}),
        input=dict(data.get("input") or {}),
        mock_prediction=dict(data.get("mock_prediction") or {}),
        source=str(data.get("source") or "authored"),
    )


__all__ = [
    "SCENARIO_FAMILIES",
    "VALID_KINDS",
    "GoldenCase",
    "GroundTruth",
    "case_from_dict",
    "load_case",
]
