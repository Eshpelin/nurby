"""Golden-set case schema for real-footage evaluation (#214).

The mocked agent-eval suite (``services/agent/eval/runner.py``) is a fast,
deterministic *regression* gate at $0.00 against scripted fixtures. It is
explicitly not an accuracy claim. This golden set is the accuracy yardstick:
labeled real footage that a provider/model/prompt is scored against, so a
model swap or prompt change is measured, not assumed.

Design constraints from the issue:

* **Footage stays out of git.** A case stores a media *reference* (a path
  plus a sha256 hash), never the bytes. Runs that need pixels resolve the
  path locally; CI and unit tests use ``recorded_output`` (a previously
  captured model output) so scoring is deterministic with no footage.
* **Scenario families with minimum counts**, including true "no event".
* **Grows from real failures** (#195): an ``incorrect`` reviewed alert can
  be turned into a case with no manual schema work (see ``intake.py``).

Two case kinds:

* ``caption`` - score a VLM description of a frame/clip for faithfulness
  and event presence/absence.
* ``ask`` - score an Ask answer against a known correct answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Scenario families the golden set must cover, with the minimum number of
# cases each (AC: "covers all listed scenario families with minimum counts,
# including true no-event cases"). Counts are deliberately modest so the set
# is buildable; raise them as footage is collected.
SCENARIO_FAMILIES: dict[str, int] = {
    "delivery": 10,
    "known_face": 10,
    "ambiguous_face": 10,
    "no_event": 15,          # true negatives matter most for false-alert rate
    "night_ir": 10,
    "rain_obscured": 8,
    "missing_recording": 5,
}

CASE_KINDS = ("caption", "ask")

# Where curated + intake cases live. Footage is NOT here.
GOLDEN_DIR = Path(__file__).resolve().parents[4] / "tests" / "agent_fixtures" / "golden"


@dataclass
class MediaRef:
    """A pointer to footage kept outside git.

    ``sha256`` pins the exact bytes so a scorecard is attributable to a
    specific clip even after the file moves. ``path`` is resolved only when
    a real run needs pixels; it may be absent on a machine that only has the
    labels.
    """

    sha256: str
    path: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in {"sha256": self.sha256, "path": self.path, "note": self.note}.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MediaRef":
        return cls(sha256=d["sha256"], path=d.get("path"), note=d.get("note"))


@dataclass
class GroundTruth:
    """The labeled answer for a case.

    ``event_present`` is the closed-vocabulary anchor used for the
    presence/absence accuracy metric. ``reference`` is the human-written
    correct caption / answer used by the LLM-as-judge. ``must_include`` /
    ``must_not_include`` are deterministic closed-vocab checks that do not
    need a judge (e.g. a delivery caption must not say "person left with a
    package").
    """

    event_present: bool
    reference: str = ""
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_present": self.event_present,
            "reference": self.reference,
            "must_include": self.must_include,
            "must_not_include": self.must_not_include,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GroundTruth":
        return cls(
            event_present=bool(d["event_present"]),
            reference=d.get("reference", ""),
            must_include=list(d.get("must_include", [])),
            must_not_include=list(d.get("must_not_include", [])),
        )


@dataclass
class GoldenCase:
    id: str
    family: str
    kind: str                       # "caption" | "ask"
    truth: GroundTruth
    media: MediaRef | None = None
    question: str | None = None     # required for "ask"
    prompt: str | None = None       # caption prompt used, when pinned
    # A previously captured model output, so CI / unit tests can score
    # without footage or a live model. Real runs ignore this.
    recorded_output: str | None = None
    source: str = "curated"         # "curated" | "feedback:<event_id>"

    def __post_init__(self) -> None:
        if self.family not in SCENARIO_FAMILIES:
            raise ValueError(f"unknown scenario family: {self.family!r}")
        if self.kind not in CASE_KINDS:
            raise ValueError(f"unknown case kind: {self.kind!r}")
        if self.kind == "ask" and not self.question:
            raise ValueError(f"ask case {self.id!r} needs a question")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "family": self.family,
            "kind": self.kind,
            "truth": self.truth.to_dict(),
            "source": self.source,
        }
        if self.media is not None:
            out["media"] = self.media.to_dict()
        for k in ("question", "prompt", "recorded_output"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GoldenCase":
        return cls(
            id=d["id"],
            family=d["family"],
            kind=d["kind"],
            truth=GroundTruth.from_dict(d["truth"]),
            media=MediaRef.from_dict(d["media"]) if d.get("media") else None,
            question=d.get("question"),
            prompt=d.get("prompt"),
            recorded_output=d.get("recorded_output"),
            source=d.get("source", "curated"),
        )


def load_cases(directory: Path | None = None) -> list[GoldenCase]:
    """Load every ``*.json`` golden case from ``directory`` (default
    :data:`GOLDEN_DIR`), sorted by id for stable scorecards."""
    directory = directory or GOLDEN_DIR
    cases: list[GoldenCase] = []
    for p in sorted(directory.glob("*.json")):
        cases.append(GoldenCase.from_dict(json.loads(p.read_text(encoding="utf-8"))))
    return cases


def save_case(case: GoldenCase, directory: Path | None = None) -> Path:
    """Write a case as ``<id>.json``. Returns the path written."""
    directory = directory or GOLDEN_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case.id}.json"
    path.write_text(json.dumps(case.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def coverage(cases: list[GoldenCase]) -> dict[str, int]:
    """Count cases per family."""
    counts = dict.fromkeys(SCENARIO_FAMILIES, 0)
    for c in cases:
        counts[c.family] = counts.get(c.family, 0) + 1
    return counts


def coverage_gaps(cases: list[GoldenCase]) -> dict[str, tuple[int, int]]:
    """Families short of their minimum, as ``{family: (have, need)}``.
    Empty dict means the set satisfies the required coverage."""
    counts = coverage(cases)
    gaps: dict[str, tuple[int, int]] = {}
    for family, need in SCENARIO_FAMILIES.items():
        have = counts.get(family, 0)
        if have < need:
            gaps[family] = (have, need)
    return gaps
