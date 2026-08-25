"""Empty completions must not look like success (issue #137).

The driver's final-answer branch is reached when a response carries no
tool calls. It then stored whatever text came back, which for an empty
completion is ``""``, with ``status="completed"``. The done event fired
normally. From the outside that is indistinguishable from a real answer,
and it is worse than a visible failure in two ways: the user gets a blank
reply with no explanation, and every quality metric computed over run
status counts it as a success.

Empty completions are ordinary provider behaviour, not a hypothetical.
They come from a safety filter, a reasoning model spending its whole
budget on thinking, a stop sequence that fires immediately, or a bad
sampling draw.

The guard tracks a **consecutive** streak, because one empty completion
followed by a real answer is noise, while three in a row is a model that
is not going to produce an answer this run. Each attempt is recorded with
its signature, so a repeat under identical conditions can be told apart
from one where the provider or model changed underneath.

The retry budget shrinks once a streak has cost real money. A model
failing expensively should not be retried into a hole: the point of a
retry is that it is cheap relative to the answer it might recover.

Pure. The driver owns the loop and the money; this owns the decision.
"""

from __future__ import annotations

from dataclasses import dataclass

# Attempts allowed while a streak is cheap. Three covers a transient bad
# draw without turning a systematically-empty model into a spin.
DEFAULT_EMPTY_RETRY_BUDGET = 3

# Attempts allowed once the streak has cost more than the threshold.
REDUCED_EMPTY_RETRY_BUDGET = 1

# Cents of streak cost past which the budget drops. Deliberately small:
# this is money spent producing nothing at all.
DEFAULT_COST_THRESHOLD_CENTS = 25


@dataclass(frozen=True)
class EmptyAttempt:
    """One observed empty completion within the current streak."""

    provider: str
    model: str
    stop_reason: str

    @property
    def signature(self) -> tuple:
        """What made this attempt what it was.

        Two attempts sharing a signature failed under identical
        conditions, which is weaker evidence that another try will differ
        than an attempt made after the provider or model changed.
        """
        return (self.provider, self.model, self.stop_reason)


def is_empty_answer(text: str | None, tool_uses: list | None) -> bool:
    """Whether a response ended the run without saying anything.

    A response carrying tool calls is not an answer at all, empty or
    otherwise, and is not this guard's business. Whitespace-only text
    counts as empty: a reply of ``"\\n\\n"`` is blank to a reader. Pure.
    """
    if tool_uses:
        return False
    return not (text or "").strip()


def retry_budget(
    streak_cost_cents: int,
    threshold_cents: int = DEFAULT_COST_THRESHOLD_CENTS,
) -> int:
    """How many empty completions to tolerate at this streak cost. Pure."""
    if streak_cost_cents >= threshold_cents:
        return REDUCED_EMPTY_RETRY_BUDGET
    return DEFAULT_EMPTY_RETRY_BUDGET


def should_retry(
    attempts: list[EmptyAttempt],
    streak_cost_cents: int = 0,
    threshold_cents: int = DEFAULT_COST_THRESHOLD_CENTS,
) -> bool:
    """Whether to ask again after the empties recorded so far. Pure."""
    return len(attempts) < retry_budget(streak_cost_cents, threshold_cents)


def nudge_for(attempts: list[EmptyAttempt]) -> str:
    """The message appended when asking again.

    Says what went wrong rather than repeating the question, because the
    model has already seen the question and answering it is exactly what
    it just failed to do. Pure.
    """
    if len(attempts) >= 2:
        return (
            "Your last two replies were empty. Answer now in plain prose,"
            " using only the evidence already gathered. Do not call any"
            " more tools, and do not reply with an empty message."
        )
    return (
        "Your last reply was empty. Please answer the question in plain"
        " prose using the evidence gathered so far."
    )


def describe(attempts: list[EmptyAttempt]) -> str:
    """A sentence for the run's error_message. Pure."""
    if not attempts:
        return "the model returned no answer"
    last = attempts[-1]
    repeated = len({a.signature for a in attempts}) == 1
    detail = (
        f"{last.provider}/{last.model} returned {len(attempts)} empty "
        f"{'reply' if len(attempts) == 1 else 'replies'}"
    )
    if repeated and len(attempts) > 1:
        detail += " under identical conditions"
    return detail
