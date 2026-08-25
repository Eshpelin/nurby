"""Provider failure classification and retry (issue #133).

llm_call had no retry at all, so a single 429 lost a whole investigation
along with every tool result already paid for. These tests pin what each
failure means, and the two places where retrying would be worse than
failing: when it cannot help, and when the answer has already started
streaming to the user.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from services.agent.failure import (
    Action,
    Failure,
    FailureKind,
    LLMCallError,
    backoff_delay,
    classify,
    classify_status,
)


def _http_error(status, body="", headers=None):
    request = httpx.Request("POST", "https://example.test/v1/messages")
    response = httpx.Response(
        status, text=body, headers=headers or {}, request=request
    )
    return httpx.HTTPStatusError("boom", request=request, response=response)


# ---- the distinction that matters ---------------------------------------


def test_our_rate_limit_waits():
    f = classify_status(429, "rate limit exceeded for requests")
    assert f.kind is FailureKind.rate_limit
    assert f.action is Action.retry


def test_upstream_rate_limit_switches_model_instead_of_waiting():
    """Both arrive as 429 and need opposite fixes. Our key is healthy, so
    waiting does nothing; the model behind the aggregator is the problem."""
    f = classify_status(429, "upstream provider is rate limited")
    assert f.kind is FailureKind.upstream_rate_limit
    assert f.action is Action.fallback


def test_no_available_provider_is_upstream():
    f = classify_status(429, "No available provider for this model")
    assert f.action is Action.fallback


def test_a_429_that_is_really_an_empty_wallet_does_not_retry():
    """Waiting never refills a prepaid balance."""
    f = classify_status(429, "insufficient credits remaining")
    assert f.kind is FailureKind.billing
    assert f.action is Action.abort


# ---- terminal failures ---------------------------------------------------


def test_auth_aborts_rather_than_retrying():
    """One credential per provider row and nothing to rotate to, so
    retrying the same rejected key is guaranteed waste."""
    for status in (401, 403):
        f = classify_status(status)
        assert f.kind is FailureKind.auth
        assert f.action is Action.abort
        assert f.recoverable is False


def test_billing_aborts():
    assert classify_status(402).action is Action.abort


def test_bad_request_aborts():
    f = classify_status(400, "unexpected field 'toolz'")
    assert f.kind is FailureKind.bad_request
    assert f.action is Action.abort


def test_context_length_falls_back_rather_than_retrying():
    """The same prompt will not fit on a retry. A bigger window might."""
    f = classify_status(400, "This model's maximum context length is 8192 tokens")
    assert f.kind is FailureKind.context_length
    assert f.action is Action.fallback


def test_unknown_4xx_is_not_retried():
    """Hammering a provider that is telling us we are wrong is rude and
    pointless."""
    assert classify_status(418).action is Action.abort


# ---- transient failures --------------------------------------------------


def test_overload_retries():
    for status in (500, 502, 503, 529):
        f = classify_status(status)
        assert f.kind is FailureKind.overloaded
        assert f.action is Action.retry


def test_transport_failures_retry():
    assert classify(httpx.ConnectTimeout("slow")).action is Action.retry
    assert classify(httpx.ReadTimeout("slow")).action is Action.retry
    assert classify(httpx.RemoteProtocolError("cut")).kind is FailureKind.protocol
    assert classify(httpx.ConnectError("no route")).kind is FailureKind.connection


def test_unsupported_provider_aborts():
    from services.agent.llm import LLMProviderUnsupportedError

    f = classify(LLMProviderUnsupportedError("no tool use"))
    assert f.kind is FailureKind.unsupported
    assert f.action is Action.abort


def test_classify_reads_an_http_status_error():
    f = classify(_http_error(529, "overloaded"))
    assert f.kind is FailureKind.overloaded
    assert f.status_code == 529


def test_an_unrecognized_exception_aborts_rather_than_looping():
    f = classify(ValueError("what"))
    assert f.action is Action.abort
    assert "ValueError" in f.message


# ---- the message the user sees -------------------------------------------


def test_messages_never_carry_the_provider_body():
    """An error body can be an HTML page or carry a key fragment."""
    secret = "sk-live-abcdef123456"
    f = classify_status(401, f"invalid key {secret}")
    assert secret not in f.message
    assert "Settings" in f.message


# ---- backoff -------------------------------------------------------------


def test_retry_after_is_honoured():
    f = classify_status(429, "slow down", {"retry-after": "3"})
    assert f.retry_after == 3.0
    assert backoff_delay(1, f.retry_after) == 3.0


def test_an_absurd_retry_after_is_ignored():
    """A provider asking for an hour is an outage, not a retry."""
    assert classify_status(429, "", {"retry-after": "3600"}).retry_after is None


def test_a_malformed_retry_after_is_ignored():
    assert classify_status(429, "", {"retry-after": "Wed, 21 Oct 2026"}).retry_after is None


def test_backoff_grows_and_is_capped():
    assert all(0 <= backoff_delay(1) <= 0.5 for _ in range(20))
    assert all(0 <= backoff_delay(3) <= 2.0 for _ in range(20))
    assert all(0 <= backoff_delay(99) <= 8.0 for _ in range(20))


def test_backoff_is_jittered():
    """Several runs failing at once must not retry in lockstep and
    recreate the burst that throttled them."""
    draws = {backoff_delay(4) for _ in range(50)}
    assert len(draws) > 1


# ---- llm_call retry behaviour -------------------------------------------


def _provider():
    return SimpleNamespace(kind="anthropic", api_key="k", base_url=None,
                           default_model="m")


async def _call(monkeypatch, side_effects, stream_callback=None, attempts=3):
    from services.agent import llm as llm_mod

    calls = {"n": 0}

    async def fake_dispatch(provider, model, system_prompt, messages, tools,
                            max_tokens, stream, cb):
        i = calls["n"]
        calls["n"] += 1
        effect = side_effects[min(i, len(side_effects) - 1)]
        if callable(effect):
            return await effect(cb)
        if isinstance(effect, Exception):
            raise effect
        return effect

    async def fake_setting(key, default=None):
        return attempts

    monkeypatch.setattr(llm_mod, "_dispatch", fake_dispatch)
    monkeypatch.setattr(llm_mod, "get_setting", fake_setting)

    # Skip the real backoff. Bind the genuine sleep first: llm_mod.asyncio
    # IS the asyncio module, so a lambda calling asyncio.sleep would call
    # the patch and recurse.
    real_sleep = asyncio.sleep

    async def no_wait(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(llm_mod.asyncio, "sleep", no_wait)

    result = await llm_mod.llm_call(
        provider=_provider(), model="m", system_prompt="s", messages=[],
        tools=[], stream=bool(stream_callback), stream_callback=stream_callback,
    )
    return result, calls["n"]


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_and_succeeds(monkeypatch):
    from services.agent.llm import LLMResponse

    ok = LLMResponse(stop_reason="end_turn", text="hello")
    result, n = await _call(monkeypatch, [_http_error(529), ok])

    assert result.text == "hello"
    assert n == 2


@pytest.mark.asyncio
async def test_retries_are_bounded(monkeypatch):
    with pytest.raises(LLMCallError) as caught:
        await _call(monkeypatch, [_http_error(503)], attempts=3)

    assert caught.value.attempts == 3
    assert caught.value.kind is FailureKind.overloaded


@pytest.mark.asyncio
async def test_a_terminal_failure_is_not_retried(monkeypatch):
    with pytest.raises(LLMCallError) as caught:
        await _call(monkeypatch, [_http_error(401)])

    assert caught.value.attempts == 1
    assert caught.value.action is Action.abort


@pytest.mark.asyncio
async def test_a_fallback_failure_is_not_retried_here(monkeypatch):
    """Switching provider is the driver's decision, not this layer's."""
    with pytest.raises(LLMCallError) as caught:
        await _call(monkeypatch, [_http_error(429, "upstream is rate limited")])

    assert caught.value.attempts == 1
    assert caught.value.action is Action.fallback


@pytest.mark.asyncio
async def test_a_stream_that_already_emitted_is_never_retried(monkeypatch):
    """A retry re-runs the whole request, so anything already shown to the
    user would arrive twice. A duplicated half answer is worse than a
    clean failure."""
    seen = []

    async def collect(delta):
        seen.append(delta)

    async def half_then_die(cb):
        await cb("The cat ")
        raise _http_error(529)

    with pytest.raises(LLMCallError):
        await _call(monkeypatch, [half_then_die], stream_callback=collect)

    assert seen == ["The cat "]  # not doubled


@pytest.mark.asyncio
async def test_a_stream_that_failed_before_emitting_is_retried(monkeypatch):
    from services.agent.llm import LLMResponse

    seen = []

    async def collect(delta):
        seen.append(delta)

    async def die_early(cb):
        raise _http_error(529)

    async def succeed(cb):
        await cb("hello")
        return LLMResponse(stop_reason="end_turn", text="hello")

    result, n = await _call(
        monkeypatch, [die_early, succeed], stream_callback=collect
    )

    assert n == 2
    assert seen == ["hello"]
    assert result.text == "hello"


# ---- the error surface ---------------------------------------------------


def test_failure_recoverability_maps_to_the_action():
    assert Failure(FailureKind.overloaded, Action.retry, "x").recoverable is True
    assert Failure(FailureKind.context_length, Action.fallback, "x").recoverable is True
    assert Failure(FailureKind.auth, Action.abort, "x").recoverable is False
