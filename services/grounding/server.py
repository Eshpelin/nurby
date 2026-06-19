"""Grounding inference microservice (the only GPU-touching code).

A tiny FastAPI app that loads LocateAnything-3B and answers ``POST /ground``.
Everything heavy (torch, transformers, the model) is imported lazily inside
functions so this module imports cleanly without a GPU and is never run in CI
(design §10. it is smoke-tested behind a GPU marker on real hardware only).

The client (``client.py``) owns parsing/rescale/caching/gating; this service
just turns an image + prompt into the model's raw ``<box>`` text.

Weights are fetched once, on first need, from the Nurby mirror
(``GROUNDING_MIRROR_URL``) for a one-click, token-free, Ollama-style download
(design §4). After that the runtime is fully offline (``HF_HUB_OFFLINE=1``).
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import tarfile
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared.config import settings

logger = logging.getLogger("nurby.grounding.server")

app = FastAPI(title="Nurby Grounding", version="0.1.0")

# Module-level model handles + status, populated lazily. Kept here (not in a
# class) so the single worker process shares one model.
_STATE: dict = {
    "model": None,
    "processor": None,
    "loading": False,
    "downloading": False,
    "download_pct": None,
    "error": None,
}
_LOAD_LOCK = asyncio.Lock()


class GroundRequest(BaseModel):
    image_b64: str
    prompt: str
    mode: str = "hybrid"
    max_new_tokens: int = 8192


class GroundResponse(BaseModel):
    raw: str
    model_revision: str | None = None


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok" if _STATE["model"] is not None else "cold",
        "model_loaded": _STATE["model"] is not None,
        "downloading": _STATE["downloading"],
        "download_pct": _STATE["download_pct"],
        "model": settings.grounding_model_id,
        "revision": settings.grounding_model_revision,
        "error": _STATE["error"],
    }


@app.post("/ground", response_model=GroundResponse)
async def ground(req: GroundRequest) -> GroundResponse:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="empty prompt")
    try:
        await _ensure_loaded()
    except Exception as exc:
        logger.exception("model load failed")
        raise HTTPException(status_code=503, detail=f"model unavailable: {exc}") from exc

    try:
        image = _decode_image(req.image_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"bad image: {exc}") from exc

    # The blocking generate runs in a thread so the event loop stays free.
    raw = await asyncio.to_thread(
        _run_inference, image, req.prompt, req.mode, req.max_new_tokens,
    )
    return GroundResponse(raw=raw, model_revision=settings.grounding_model_revision)


# ── model lifecycle ────────────────────────────────────────────────────


async def _ensure_loaded() -> None:
    if _STATE["model"] is not None:
        return
    async with _LOAD_LOCK:
        if _STATE["model"] is not None:
            return
        await _ensure_weights()
        _STATE["loading"] = True
        try:
            await asyncio.to_thread(_load_model)
            _STATE["error"] = None
        finally:
            _STATE["loading"] = False


async def _ensure_weights() -> None:
    """Make sure the weights are present, downloading from the mirror if not.

    This is the "click → it just downloads" path (design §4). The mirror
    serves a single tar.gz of the pinned snapshot, so there is no HF token and
    no license click at runtime (consent was captured at install/enable).
    """
    dest = Path(settings.grounding_weights_dir)
    if dest.exists() and any(dest.iterdir()):
        return

    mirror = settings.grounding_mirror_url
    dest.mkdir(parents=True, exist_ok=True)
    if mirror:
        tar_name = (
            f"{settings.grounding_model_id.replace('/', '_')}"
            f"-{settings.grounding_model_revision}.tar.gz"
        )
        url = f"{mirror.rstrip('/')}/{tar_name}"
        logger.info("downloading grounding weights from mirror %s", url)
        _STATE["downloading"] = True
        _STATE["download_pct"] = 0
        try:
            await _download_and_extract(url, dest)
        finally:
            _STATE["downloading"] = False
            _STATE["download_pct"] = None
        return

    # No mirror configured. fall back to a token-gated HuggingFace pull.
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise RuntimeError(
            "grounding weights missing and no GROUNDING_MIRROR_URL or HF_TOKEN set. "
            "Run scripts/setup-grounding.sh."
        )
    from huggingface_hub import snapshot_download

    await asyncio.to_thread(
        snapshot_download,
        repo_id=settings.grounding_model_id,
        revision=settings.grounding_model_revision,
        local_dir=str(dest),
        token=token,
    )


async def _download_and_extract(url: str, dest: Path) -> None:
    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as http:
        async with http.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            seen = 0
            buf = io.BytesIO()
            async for chunk in resp.aiter_bytes(1 << 20):
                buf.write(chunk)
                seen += len(chunk)
                if total:
                    _STATE["download_pct"] = round(100 * seen / total, 1)
    buf.seek(0)
    # Extract on a thread (CPU/IO bound). filter="data" rejects unsafe members.
    await asyncio.to_thread(_safe_extract, buf, dest)


def _safe_extract(buf: io.BytesIO, dest: Path) -> None:
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        try:
            tar.extractall(dest, filter="data")  # py3.12+: blocks path traversal
        except TypeError:
            tar.extractall(dest)


def _load_model() -> None:
    import torch
    from transformers import AutoModel, AutoProcessor

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    src = settings.grounding_weights_dir
    logger.info("loading grounding model from %s (bf16)", src)
    processor = AutoProcessor.from_pretrained(src, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        src,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    if torch.cuda.is_available():
        model = model.to("cuda")
    model.eval()
    _STATE["processor"] = processor
    _STATE["model"] = model


def _decode_image(image_b64: str):
    from PIL import Image

    data = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    # Decompression-bomb guard mirrors the client cap (§9).
    cap = settings.grounding_max_image_px
    if max(img.size) > cap:
        img.thumbnail((cap, cap))
    return img


def _run_inference(image, prompt: str, mode: str, max_new_tokens: int) -> str:
    """Generate the model's raw coordinate text.

    NOTE: the exact processor/generate call must be confirmed against the
    LocateAnything-3B model card when wiring real hardware (the model ships
    custom modeling code via trust_remote_code). This follows the standard
    transformers VLM shape and is intentionally never exercised in CI.
    """
    import torch

    model = _STATE["model"]
    processor = _STATE["processor"]
    inputs = processor(images=image, text=prompt, return_tensors="pt")
    if torch.cuda.is_available():
        inputs = {k: v.to("cuda") for k, v in inputs.items()}
    gen_kwargs = {"max_new_tokens": max_new_tokens}
    # The model card exposes fast | slow | hybrid via generation_mode.
    if mode:
        gen_kwargs["generation_mode"] = mode
    with torch.inference_mode():
        out = model.generate(**inputs, **gen_kwargs)
    text = processor.batch_decode(out, skip_special_tokens=False)[0]
    return text


def main() -> None:  # pragma: no cover - container entrypoint
    import uvicorn

    port = int(os.environ.get("GROUNDING_PORT", "8800"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
