"""Shared LLM call retry + error reporting.

VLM and text LLM calls used to swallow httpx errors silently. The
worker would log and move on, leaving the user with no UI signal.
This module centralizes:

- Retry on 429 / 5xx with capped exponential backoff. Honors
  ``Retry-After`` when the provider sends one.
- Failure broadcast as ``llm_error`` over the WS channel so the
  dashboard can show a toast with the provider name and HTTP code.

Importable from any call site without tying to perception. Tests can
swap the broadcast hook with a no-op fixture.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

logger = logging.getLogger("nurby.perception.llm_errors")


_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}
DEFAULT_MAX_ATTEMPTS = 3


async def call_with_retry(
    func,
    *,
    provider_name: str,
    provider_kind: str,
    op: str,
    camera_id: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
):
    """Run an async ``func()`` that performs a single httpx request.

    Retries on httpx.HTTPStatusError when the status is in the
    retryable set, on httpx.TimeoutException, and on
    httpx.TransportError. Other exceptions propagate.

    On terminal failure broadcasts ``llm_error`` and returns None.
    """
    attempt = 0
    last_exc: Exception | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return await func()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            last_exc = exc
            retry_after = _retry_after_seconds(exc)
            if status in _RETRYABLE and attempt < max_attempts:
                delay = retry_after if retry_after is not None else _backoff(attempt)
                logger.warning(
                    "%s %s -> HTTP %d, retrying in %.1fs (attempt %d/%d)",
                    provider_kind, op, status, delay, attempt, max_attempts,
                )
                await asyncio.sleep(delay)
                continue
            await _broadcast_error(
                provider_name=provider_name,
                provider_kind=provider_kind,
                op=op,
                camera_id=camera_id,
                message=f"HTTP {status}",
                status=status,
            )
            logger.warning(
                "%s %s -> HTTP %d, giving up after %d attempts",
                provider_kind, op, status, attempt,
            )
            return None
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = _backoff(attempt)
                logger.warning(
                    "%s %s transport error, retrying in %.1fs (attempt %d/%d): %s",
                    provider_kind, op, delay, attempt, max_attempts, exc,
                )
                await asyncio.sleep(delay)
                continue
            await _broadcast_error(
                provider_name=provider_name,
                provider_kind=provider_kind,
                op=op,
                camera_id=camera_id,
                message=str(exc) or "transport error",
                status=0,
            )
            return None
    if last_exc is not None:
        logger.exception("LLM call exhausted retries", exc_info=last_exc)
    return None


def _retry_after_seconds(exc: httpx.HTTPStatusError) -> float | None:
    if exc.response is None:
        return None
    raw = exc.response.headers.get("retry-after")
    if not raw:
        return None
    try:
        # Spec allows seconds-as-int or HTTP-date. We only handle int
        # because that's what every cloud LLM emits.
        return float(raw)
    except ValueError:
        return None


def _backoff(attempt: int) -> float:
    """Capped exponential backoff with jitter. 1, 2, 4 ... up to 30s."""
    base = min(30.0, 1.0 * (2 ** (attempt - 1)))
    return base + random.uniform(0, base * 0.25)


async def _broadcast_error(
    *,
    provider_name: str,
    provider_kind: str,
    op: str,
    camera_id: str | None,
    message: str,
    status: int,
) -> None:
    """Fire a llm_error WS event so the UI can surface a toast."""
    payload: dict[str, Any] = {
        "type": "llm_error",
        "provider_name": provider_name,
        "provider_kind": provider_kind,
        "op": op,
        "camera_id": camera_id,
        "status": status,
        "message": message,
    }
    try:
        # Lazy import to keep this module dependency-light.
        from services.api.ws import broadcast as ws_broadcast

        await ws_broadcast(payload)
    except Exception:
        # WS broadcast is best-effort. The actual call already failed;
        # logging is enough.
        logger.debug("llm_error broadcast failed", exc_info=True)
