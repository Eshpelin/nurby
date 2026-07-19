"""GroundingClient. the single HTTP seam to the grounding model.

Everything Nurby does with grounding goes through ``GroundingClient.ground``:
it encodes the frame, enforces the global GPU gate, sends one HTTP request to
the grounding service (local microservice or remote endpoint), parses the
``<box>`` output, rescales to pixels, and caches the result. The only
GPU-touching code lives in ``server.py``; this client is pure I/O and is
fakeable in CI by passing a ``responder`` (design §10).
"""

from __future__ import annotations

import base64
import hashlib
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import httpx
import numpy as np

from services.grounding.config import GroundingBackend, is_enabled, resolve_backend, resolve_mode
from services.grounding.gate import PriorityGate, get_gate
from services.grounding.parse import GroundedBox, parse_grounding_output
from shared.config import settings

logger = logging.getLogger("nurby.grounding.client")


@dataclass
class GroundingResult:
    """Outcome of one grounding call.

    ``found`` is True when at least one box came back. ``error`` is set when
    the call could not run (disabled, misconfigured, network/model failure);
    an empty-but-successful scan is ``found=False, error=None`` (= "not
    found"), which is a meaningful, trustworthy answer.
    """

    found: bool = False
    boxes: list[GroundedBox] = field(default_factory=list)
    raw: str = ""
    error: str | None = None
    model_revision: str | None = None
    backend: str | None = None
    cached: bool = False
    leaves_privacy_boundary: bool = False


# A responder lets tests/fakes stand in for the GPU: given (prompt, frame) it
# returns the raw model text. When set, the HTTP call is skipped but the gate,
# parser, rescale, and cache still run.
Responder = Callable[[str, np.ndarray], str]


class GroundingClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        gate: PriorityGate | None = None,
        responder: Responder | None = None,
        cache_size: int = 128,
    ):
        self._http = http
        self._gate = gate or get_gate()
        self._responder = responder
        self._cache: OrderedDict[str, GroundingResult] = OrderedDict()
        self._cache_size = cache_size

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=settings.grounding_request_timeout_s)
        return self._http

    async def ground(
        self,
        frame: np.ndarray,
        prompt: str,
        *,
        interactive: bool = True,
        mode: str | None = None,
        max_boxes: int | None = None,
        timeout: float | None = None,
    ) -> GroundingResult:
        """Locate ``prompt`` in ``frame``. Never raises; failures come back as
        ``GroundingResult.error`` so callers (search, rules) degrade cleanly.
        """
        prompt = (prompt or "").strip()
        if not prompt:
            return GroundingResult(error="empty prompt")
        if frame is None or getattr(frame, "size", 0) == 0:
            return GroundingResult(error="empty frame")

        if not await is_enabled():
            return GroundingResult(error="grounding is disabled")

        backend = await resolve_backend()
        if backend.error:
            return GroundingResult(error=backend.error, backend=backend.kind)

        max_boxes = max_boxes or settings.grounding_max_boxes
        resolved_mode = await resolve_mode(mode)

        try:
            b64, width, height = self._encode(frame)
        except Exception as exc:  # decode/encode guard before the GPU (§9)
            logger.warning("grounding frame encode failed: %s", exc)
            return GroundingResult(error=f"frame encode failed: {exc}", backend=backend.kind)

        cache_key = self._cache_key(b64, prompt, resolved_mode)
        hit = self._cache.get(cache_key)
        if hit is not None:
            self._cache.move_to_end(cache_key)
            return GroundingResult(
                found=hit.found, boxes=list(hit.boxes), raw=hit.raw,
                model_revision=hit.model_revision, backend=backend.kind,
                cached=True, leaves_privacy_boundary=backend.leaves_privacy_boundary,
            )

        try:
            async with self._gate.slot(interactive=interactive):
                raw, revision = await self._infer(
                    backend, b64, prompt, resolved_mode, frame, timeout,
                )
        except httpx.HTTPError as exc:
            logger.warning("grounding request failed (%s): %s", backend.kind, exc)
            return GroundingResult(error=f"grounding request failed: {exc}", backend=backend.kind)
        except Exception as exc:
            logger.exception("grounding call errored")
            return GroundingResult(error=f"grounding error: {exc}", backend=backend.kind)

        boxes = parse_grounding_output(raw, width, height, label=prompt, max_boxes=max_boxes)
        result = GroundingResult(
            found=bool(boxes), boxes=boxes, raw=raw,
            model_revision=revision, backend=backend.kind,
            leaves_privacy_boundary=backend.leaves_privacy_boundary,
        )
        self._cache_put(cache_key, result)
        return result

    async def ground_batch(
        self,
        frame: np.ndarray,
        prompts: list[str],
        *,
        interactive: bool = True,
        mode: str | None = None,
        max_boxes: int | None = None,
        timeout: float | None = None,
    ) -> list[GroundingResult]:
        """Locate several prompts in ONE frame with a single backend call.
        Returns results aligned to ``prompts``. Per-prompt cache is honored (only
        misses are sent). Never raises."""
        prompts = [(p or "").strip() for p in (prompts or [])]
        out: list[GroundingResult | None] = [None] * len(prompts)
        if not prompts:
            return []
        if frame is None or getattr(frame, "size", 0) == 0:
            return [GroundingResult(error="empty frame") for _ in prompts]
        if not await is_enabled():
            return [GroundingResult(error="grounding is disabled") for _ in prompts]
        backend = await resolve_backend()
        if backend.error:
            return [GroundingResult(error=backend.error, backend=backend.kind) for _ in prompts]

        max_boxes = max_boxes or settings.grounding_max_boxes
        resolved_mode = await resolve_mode(mode)
        try:
            b64, width, height = self._encode(frame)
        except Exception as exc:
            return [GroundingResult(error=f"frame encode failed: {exc}", backend=backend.kind) for _ in prompts]

        misses: list[tuple[int, str]] = []
        for i, p in enumerate(prompts):
            if not p:
                out[i] = GroundingResult(error="empty prompt", backend=backend.kind)
                continue
            key = self._cache_key(b64, p, resolved_mode)
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                out[i] = GroundingResult(
                    found=hit.found, boxes=list(hit.boxes), raw=hit.raw,
                    model_revision=hit.model_revision, backend=backend.kind,
                    cached=True, leaves_privacy_boundary=backend.leaves_privacy_boundary,
                )
            else:
                misses.append((i, p))

        if misses:
            try:
                async with self._gate.slot(interactive=interactive):
                    raws = await self._infer_batch(
                        backend, b64, [p for _, p in misses], resolved_mode, frame, timeout,
                    )
            except httpx.HTTPError as exc:
                logger.warning("grounding batch request failed (%s): %s", backend.kind, exc)
                for i, _p in misses:
                    out[i] = GroundingResult(error=f"grounding request failed: {exc}", backend=backend.kind)
                return [r for r in out if r is not None]
            except Exception as exc:
                logger.exception("grounding batch errored")
                for i, _p in misses:
                    out[i] = GroundingResult(error=f"grounding error: {exc}", backend=backend.kind)
                return [r for r in out if r is not None]
            for (i, p), (raw, revision) in zip(misses, raws):
                boxes = parse_grounding_output(raw, width, height, label=p, max_boxes=max_boxes)
                res = GroundingResult(
                    found=bool(boxes), boxes=boxes, raw=raw, model_revision=revision,
                    backend=backend.kind, leaves_privacy_boundary=backend.leaves_privacy_boundary,
                )
                self._cache_put(self._cache_key(b64, p, resolved_mode), res)
                out[i] = res
        return [r for r in out if r is not None]

    async def _infer_batch(
        self, backend: GroundingBackend, b64: str, prompts: list[str],
        mode: str, frame: np.ndarray, timeout: float | None,
    ) -> list[tuple[str, str | None]]:
        """Return ``(raw, model_revision)`` per prompt, in order."""
        if self._responder is not None:
            return [(self._responder(p, frame), "fake") for p in prompts]
        http = await self._get_http()
        payload = {
            "image_b64": b64,
            "prompts": prompts,
            "mode": mode,
            "max_new_tokens": settings.grounding_max_output_tokens,
        }
        resp = await http.post(
            f"{backend.base_url}/ground_batch",
            json=payload,
            timeout=timeout or settings.grounding_request_timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        rev = body.get("model_revision")
        return [(r.get("raw", "") or "", rev) for r in (body.get("results") or [])]

    async def health(self) -> dict:
        """Best-effort health of the resolved backend for the navbar surface."""
        if not await is_enabled():
            return {"enabled": False, "status": "disabled"}
        backend = await resolve_backend()
        if backend.error:
            return {"enabled": True, "status": "misconfigured", "error": backend.error}
        if self._responder is not None:
            return {"enabled": True, "status": "ok", "backend": backend.kind}
        try:
            http = await self._get_http()
            resp = await http.get(f"{backend.base_url}/health", timeout=5.0)
            resp.raise_for_status()
            body = resp.json()
            return {"enabled": True, "backend": backend.kind, **body}
        except Exception as exc:
            return {"enabled": True, "backend": backend.kind, "status": "unreachable", "error": str(exc)}

    async def warmup(self) -> dict:
        """Ask the backend to start loading the model now, so the first real
        grounding call doesn't pay the cold-start. Best-effort and fast: it
        returns without waiting for the load to finish. No-op for the in-process
        responder (already resident)."""
        if not await is_enabled():
            return {"enabled": False, "status": "disabled"}
        backend = await resolve_backend()
        if backend.error or self._responder is not None:
            return {"enabled": True, "status": "ok", "backend": backend.kind}
        try:
            http = await self._get_http()
            resp = await http.post(f"{backend.base_url}/warmup", timeout=5.0)
            resp.raise_for_status()
            return {"enabled": True, "backend": backend.kind, **resp.json()}
        except Exception as exc:
            return {"enabled": True, "backend": backend.kind, "status": "unreachable", "error": str(exc)}

    # ── internals ──────────────────────────────────────────────────────

    async def _infer(
        self,
        backend: GroundingBackend,
        b64: str,
        prompt: str,
        mode: str,
        frame: np.ndarray,
        timeout: float | None,
    ) -> tuple[str, str | None]:
        """Return ``(raw_text, model_revision)`` from the model."""
        if self._responder is not None:
            return self._responder(prompt, frame), "fake"

        http = await self._get_http()
        payload = {
            "image_b64": b64,
            "prompt": prompt,
            "mode": mode,
            "max_new_tokens": settings.grounding_max_output_tokens,
        }
        resp = await http.post(
            f"{backend.base_url}/ground",
            json=payload,
            timeout=timeout or settings.grounding_request_timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        return body.get("raw", "") or "", body.get("model_revision")

    def _encode(self, frame: np.ndarray) -> tuple[str, int, int]:
        """JPEG-encode ``frame``, downscaling if it exceeds the pixel cap.

        The cap is both a cost guard and a decompression-bomb guard (§9): the
        GPU never sees an image larger than ``grounding_max_image_px`` on its
        long edge.
        """
        h, w = frame.shape[:2]
        cap = settings.grounding_max_image_px
        long_edge = max(h, w)
        if long_edge > cap:
            scale = cap / float(long_edge)
            frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))))
            h, w = frame.shape[:2]
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError("cv2.imencode returned False")
        return base64.b64encode(buf.tobytes()).decode("utf-8"), w, h

    @staticmethod
    def _cache_key(b64: str, prompt: str, mode: str) -> str:
        # Key on the model revision, the normalized prompt, and the frame
        # content hash (design §7 cache key). The b64 already encodes content.
        digest = hashlib.sha256()
        digest.update(settings.grounding_model_revision.encode())
        digest.update(b"\0")
        digest.update(prompt.lower().encode())
        digest.update(b"\0")
        digest.update(mode.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(b64.encode()).digest())
        return digest.hexdigest()

    def _cache_put(self, key: str, result: GroundingResult) -> None:
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


_client: GroundingClient | None = None


def get_client() -> GroundingClient:
    """Process-wide grounding client (lazy)."""
    global _client
    if _client is None:
        _client = GroundingClient()
    return _client
