"""What to do when a provider call fails (issue #133).

``llm_call`` had no retry path at all. Three bare
``httpx.AsyncClient(timeout=120.0)`` blocks, every failure propagating to
the catch-all at the bottom of ``AgentDriver.run``, which marked the run
failed and showed the user a raw exception string. One 429 lost the whole
investigation, including every tool result already paid for.

This module answers one question: given an exception from a provider
call, what should happen next? It maps failures to an **action**, not to
a message, so the decision lives in one tested place instead of being
re-derived by string matching at each call site.

Two distinctions are worth being careful about.

``rate_limit`` vs ``upstream_rate_limit``. Both arrive as a 429 and need
opposite fixes. The first is our own key being throttled, and waiting
helps. The second is an aggregator telling us the model behind it is
throttled, while our key is perfectly healthy; waiting does nothing and
the fix is a different model. A household running a local model with a
cloud fallback hits this distinction routinely.

``auth`` is terminal here, not a rotation trigger. Nurby stores one
credential per Provider row and has nothing to rotate to, so retrying the
same key is guaranteed waste and the honest response is to stop and say
the key is bad. If per-provider credential pools ever land, this is the
place that changes.
"""

from __future__ import annotations

import enum
import logging
import random
import re
from dataclasses import dataclass

logger = logging.getLogger("nurby.agent.failure")


class Action(str, enum.Enum):
    """What the caller should do about a failure."""

    retry = "retry"        # transient. same provider, after a backoff
    fallback = "fallback"  # this provider/model will not work now. switch
    abort = "abort"        # nothing here will help. stop and explain


class FailureKind(str, enum.Enum):
    """Why a provider call failed."""

    rate_limit = "rate_limit"                    # 429, our key. wait
    upstream_rate_limit = "upstream_rate_limit"  # 429, their model. switch
    overloaded = "overloaded"                    # 5xx / 529. wait, then switch
    timeout = "timeout"                          # no response in time
    connection = "connection"                    # never reached them
    protocol = "protocol"                        # stream died mid-flight
    auth = "auth"                                # 401/403. bad key
    billing = "billing"                          # 402 / out of credit
    context_length = "context_length"            # prompt too large
    bad_request = "bad_request"                  # 400. our payload is wrong
    unsupported = "unsupported"                  # provider kind we cannot call
    unknown = "unknown"


# Kinds where waiting is pointless but a different model might work.
_FALLBACK_KINDS = {
    FailureKind.upstream_rate_limit,
    FailureKind.context_length,
}

# Kinds where nothing downstream helps and the user has to act.
_ABORT_KINDS = {
    FailureKind.auth,
    FailureKind.billing,
    FailureKind.bad_request,
    FailureKind.unsupported,
    FailureKind.unknown,
}


@dataclass(frozen=True)
class Failure:
    """A classified provider failure."""

    kind: FailureKind
    action: Action
    message: str
    status_code: int | None = None
    retry_after: float | None = None

    @property
    def recoverable(self) -> bool:
        """Whether anything other than the user can still fix this."""
        return self.action is not Action.abort


# Aggregators say "upstream", "provider", or name the model when the 429
# is about the model behind them rather than about our key. Narrow on
# purpose: misreading our own throttle as an upstream one would burn a
# fallback instead of simply waiting a second.
_UPSTREAM_HINTS = re.compile(
    r"upstream|provider .*(rate|limit|capacity)|model is (overloaded|rate)|"
    r"no (available )?(provider|endpoint)",
    re.IGNORECASE,
)

_CONTEXT_HINTS = re.compile(
    r"context[_ ]length|maximum context|too many tokens|prompt is too long|"
    r"reduce the length|input is too long",
    re.IGNORECASE,
)

_BILLING_HINTS = re.compile(
    r"insufficient (credit|funds|balance|quota)|billing|payment required|"
    r"exceeded your current quota",
    re.IGNORECASE,
)


def _action_for(kind: FailureKind) -> Action:
    if kind in _ABORT_KINDS:
        return Action.abort
    if kind in _FALLBACK_KINDS:
        return Action.fallback
    return Action.retry


def _retry_after(headers) -> float | None:
    """Seconds from a Retry-After header, when the provider sent one."""
    try:
        raw = (headers or {}).get("retry-after") or (headers or {}).get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        seconds = float(str(raw).strip())
    except (TypeError, ValueError):
        return None  # HTTP-date form. not worth parsing for a backoff hint
    # A provider asking us to wait an hour is not a retry, it is an outage.
    return seconds if 0 < seconds <= 120 else None


def classify_status(status: int, body: str = "", headers=None) -> Failure:
    """Classify an HTTP failure. Pure, for tests."""
    body = body or ""
    if status == 429:
        if _UPSTREAM_HINTS.search(body):
            kind = FailureKind.upstream_rate_limit
        else:
            kind = FailureKind.rate_limit
    elif status in (401, 403):
        kind = FailureKind.auth
    elif status == 402:
        kind = FailureKind.billing
    elif status == 400:
        if _CONTEXT_HINTS.search(body):
            kind = FailureKind.context_length
        elif _BILLING_HINTS.search(body):
            kind = FailureKind.billing
        else:
            kind = FailureKind.bad_request
    elif status in (408, 409, 425):
        kind = FailureKind.timeout
    elif status == 529 or 500 <= status < 600:
        kind = FailureKind.overloaded
    else:
        # Some providers answer 200-with-error or an unusual 4xx. Treating
        # an unknown 4xx as retryable would hammer them for nothing.
        kind = FailureKind.bad_request if 400 <= status < 500 else FailureKind.unknown

    # A 402 can also arrive dressed as a 429 when a prepaid balance runs
    # out. Waiting will never refill it.
    if kind is FailureKind.rate_limit and _BILLING_HINTS.search(body):
        kind = FailureKind.billing

    return Failure(
        kind=kind,
        action=_action_for(kind),
        message=_describe(kind, status, body),
        status_code=status,
        retry_after=_retry_after(headers),
    )


def classify(exc: Exception) -> Failure:
    """Classify any exception raised by a provider call. Pure, for tests."""
    import httpx

    from services.agent.llm import LLMProviderUnsupportedError

    if isinstance(exc, LLMProviderUnsupportedError):
        return Failure(
            kind=FailureKind.unsupported,
            action=Action.abort,
            message=str(exc),
        )

    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        body = ""
        try:
            body = response.text or ""
        except Exception:
            body = ""
        return classify_status(
            response.status_code, body, getattr(response, "headers", None)
        )

    if isinstance(exc, httpx.TimeoutException):
        return Failure(
            kind=FailureKind.timeout,
            action=Action.retry,
            message="the model did not respond in time",
        )
    if isinstance(exc, httpx.RemoteProtocolError):
        return Failure(
            kind=FailureKind.protocol,
            action=Action.retry,
            message="the connection to the model dropped mid-response",
        )
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return Failure(
            kind=FailureKind.connection,
            action=Action.retry,
            message="could not reach the model",
        )

    return Failure(
        kind=FailureKind.unknown,
        action=Action.abort,
        message=f"{type(exc).__name__}: {exc}",
    )


def _describe(kind: FailureKind, status: int, body: str) -> str:
    """A sentence a person can act on. Never the raw provider body, which
    can be an HTML error page or carry a key fragment."""
    return {
        FailureKind.rate_limit: "the model is rate-limiting us",
        FailureKind.upstream_rate_limit: (
            "the provider's upstream model is rate-limited"
        ),
        FailureKind.overloaded: f"the model provider is overloaded (HTTP {status})",
        FailureKind.auth: (
            "the provider rejected the API key. check it in Settings"
        ),
        FailureKind.billing: (
            "the provider account is out of credit"
        ),
        FailureKind.context_length: (
            "the conversation is too long for this model's context window"
        ),
        FailureKind.bad_request: f"the provider rejected the request (HTTP {status})",
        FailureKind.timeout: "the model did not respond in time",
    }.get(kind, f"the provider call failed (HTTP {status})")


def backoff_delay(attempt: int, retry_after: float | None = None,
                  base: float = 0.5, cap: float = 8.0) -> float:
    """Seconds to wait before attempt ``attempt`` (1-based).

    Honours a provider's Retry-After when it sent one, since that is the
    provider telling us what it wants. Otherwise exponential with full
    jitter: several agent runs failing at once must not retry in lockstep
    and re-create the burst that throttled them. Pure except for the
    jitter draw.
    """
    if retry_after is not None:
        return max(0.0, float(retry_after))
    ceiling = min(cap, base * (2 ** max(0, attempt - 1)))
    return random.uniform(0.0, ceiling)


class LLMCallError(RuntimeError):
    """A provider call that retrying could not save.

    Carries the classification so the driver can decide between switching
    provider and giving up, and can show the user a sentence instead of a
    stack trace.
    """

    def __init__(self, failure: Failure, attempts: int):
        self.failure = failure
        self.attempts = attempts
        super().__init__(failure.message)

    @property
    def action(self) -> Action:
        return self.failure.action

    @property
    def kind(self) -> FailureKind:
        return self.failure.kind
