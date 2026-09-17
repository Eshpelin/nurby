"""Provider seam for the golden harness.

The runner asks a *provider* for a prediction and never knows whether
it came from a committed replay blob or a live model. Two protocols.

- ``CaptionProvider.caption(case)`` -> ``CaptionPrediction``.
- ``AnswerProvider.answer(case)`` -> ``AnswerPrediction``.

The committed defaults (``ReplayCaptionProvider`` / ``ReplayAnswerProvider``)
read the fixture's ``mock_prediction`` block, so CI is deterministic and
needs no model, key, or footage. A live run supplies its own provider;
the ``LiveVLMCaptionProvider`` sketch below shows the one clean seam
into ``services.agent.analyzer.call_vlm_structured`` without importing
it at module load (so importing this file never drags in heavy deps).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from services.agent.eval.golden.schema import GoldenCase


@dataclass
class RunConfig:
    """Attribution stamped onto every scorecard.

    A quality claim must cite this ("prompt v3, gemini-2.0-flash: 91%
    caption faithfulness"), never the mocked agent run. ``mode`` records
    whether the numbers came from replay fixtures or a live model.
    """

    provider: str = "replay"
    model: str = "mock"
    prompt_version: str = "v0"
    mode: str = "replay"  # "replay" | "live"
    notes: str = ""


@dataclass
class CaptionPrediction:
    caption: str = ""
    event_present: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerPrediction:
    answer: str = ""
    event_present: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CaptionProvider(Protocol):
    def caption(self, case: GoldenCase) -> CaptionPrediction: ...


@runtime_checkable
class AnswerProvider(Protocol):
    def answer(self, case: GoldenCase) -> AnswerPrediction: ...


# ── Deterministic replay defaults (CI) ──────────────────────────────


class ReplayCaptionProvider:
    """Returns the fixture's committed ``mock_prediction`` caption.

    This is what makes the harness runnable in CI with zero live calls.
    A fixture with no ``mock_prediction.caption`` yields an empty
    prediction, which will (correctly) score as a miss.
    """

    provider = "replay"
    model = "mock"

    def caption(self, case: GoldenCase) -> CaptionPrediction:
        mp = case.mock_prediction or {}
        return CaptionPrediction(
            caption=str(mp.get("caption", "")),
            event_present=bool(mp.get("event_present", case.ground_truth.event_present)),
            raw=dict(mp),
        )


class ReplayAnswerProvider:
    """Returns the fixture's committed ``mock_prediction`` answer."""

    provider = "replay"
    model = "mock"

    def answer(self, case: GoldenCase) -> AnswerPrediction:
        mp = case.mock_prediction or {}
        return AnswerPrediction(
            answer=str(mp.get("answer", "")),
            event_present=bool(mp.get("event_present", case.ground_truth.event_present)),
            raw=dict(mp),
        )


# ── Live adapter sketch (opt-in, never runs in CI) ───────────────────


class LiveVLMCaptionProvider:
    """Adapter onto the real structured VLM path.

    Not exercised by CI or the test suite. It documents the single seam
    a real-footage run uses: resolve frames for the pinned footage,
    then call the production ``call_vlm_structured`` and shape its JSON
    into a ``CaptionPrediction``. Frame loading is intentionally the
    operator's responsibility (footage is not in git), supplied via
    ``frame_loader(case) -> list[np.ndarray]``.

    Kept import-light: ``call_vlm_structured`` is imported lazily inside
    ``caption`` so ``import providers`` stays cheap.
    """

    def __init__(self, provider_row: Any, frame_loader: Any, *, question: str = "Describe the scene."):
        self._provider_row = provider_row
        self._frame_loader = frame_loader
        self._question = question
        self.provider = getattr(provider_row, "kind", "live")
        self.model = getattr(provider_row, "default_model", "unknown")

    def caption(self, case: GoldenCase) -> CaptionPrediction:  # pragma: no cover - live only
        import anyio

        from services.agent.analyzer import call_vlm_structured

        frames = self._frame_loader(case)
        question = case.prompt or self._question
        parsed = anyio.from_thread.run(
            call_vlm_structured, self._provider_row, frames, question
        )
        caption = parsed.get("caption") or parsed.get("summary") or ""
        event = bool(parsed.get("event_present", parsed.get("objects")))
        return CaptionPrediction(caption=str(caption), event_present=event, raw=parsed)


__all__ = [
    "AnswerPrediction",
    "AnswerProvider",
    "CaptionPrediction",
    "CaptionProvider",
    "LiveVLMCaptionProvider",
    "ReplayAnswerProvider",
    "ReplayCaptionProvider",
    "RunConfig",
]
