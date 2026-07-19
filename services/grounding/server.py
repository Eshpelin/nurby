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
    "tokenizer": None,
    "device": None,
    "loading": False,
    "downloading": False,
    "download_pct": None,
    "error": None,
}


def _pick_device():
    """cuda > mps (Apple Silicon) > cpu. The model card targets datacenter
    GPUs, but a 3B model in bf16 (~6GB) runs on Apple Silicon's unified memory
    via Metal/MPS too, just slower."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"
_LOAD_LOCK = asyncio.Lock()


class GroundRequest(BaseModel):
    image_b64: str
    prompt: str
    mode: str = "hybrid"
    max_new_tokens: int = 8192


class GroundResponse(BaseModel):
    raw: str
    model_revision: str | None = None


class GroundBatchRequest(BaseModel):
    image_b64: str
    prompts: list[str]
    mode: str = "hybrid"
    max_new_tokens: int = 8192


class GroundBatchItem(BaseModel):
    prompt: str
    raw: str


class GroundBatchResponse(BaseModel):
    results: list[GroundBatchItem]
    model_revision: str | None = None


@app.get("/health")
async def health() -> dict:
    # Resolve the device even before the model loads so the UI can tell the
    # user whether grounding will run on a GPU (cuda), Apple Silicon (mps),
    # or fall back to (slow) cpu.
    try:
        device = _STATE["device"] or _pick_device()
    except Exception:
        device = None
    return {
        "status": "ok" if _STATE["model"] is not None else "cold",
        "model_loaded": _STATE["model"] is not None,
        "downloading": _STATE["downloading"],
        "download_pct": _STATE["download_pct"],
        "model": settings.grounding_model_id,
        "revision": settings.grounding_model_revision,
        "device": device,
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


@app.post("/ground_batch", response_model=GroundBatchResponse)
async def ground_batch(req: GroundBatchRequest) -> GroundBatchResponse:
    """Ground several prompts against ONE frame in a single request: decode the
    image once, hold the load once, run each prompt. Saves the HTTP round-trip,
    the repeat decode, and lock churn vs N /ground calls. (A true single
    forward-pass over batched prompts is a follow-up.)"""
    prompts = [p.strip() for p in (req.prompts or []) if p and p.strip()]
    if not prompts:
        raise HTTPException(status_code=400, detail="no prompts")
    try:
        await _ensure_loaded()
    except Exception as exc:
        logger.exception("model load failed")
        raise HTTPException(status_code=503, detail=f"model unavailable: {exc}") from exc
    try:
        image = _decode_image(req.image_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"bad image: {exc}") from exc

    items: list[GroundBatchItem] = []
    for p in prompts:
        raw = await asyncio.to_thread(_run_inference, image, p, req.mode, req.max_new_tokens)
        items.append(GroundBatchItem(prompt=p, raw=raw))
    return GroundBatchResponse(results=items, model_revision=settings.grounding_model_revision)


@app.post("/warmup")
async def warmup() -> dict:
    """Kick the (slow, ~6GB) model load in the background and return immediately.
    Idempotent: a no-op once warm or already loading. The first real /ground
    then doesn't pay the cold-start latency. Poll /health for readiness."""
    if _STATE["model"] is None and not _STATE["loading"]:
        _STATE["_warmup_task"] = asyncio.create_task(_ensure_loaded())
    return await health()


@app.on_event("startup")
async def _maybe_preload() -> None:
    """Optionally preload the model when the server starts so the first request
    isn't slow. Off by default; enable with GROUNDING_PRELOAD=1. Loads in the
    background so /health is up immediately."""
    if os.getenv("GROUNDING_PRELOAD", "").strip().lower() in ("1", "true", "yes", "on"):
        logger.info("GROUNDING_PRELOAD set — preloading model at startup")
        _STATE["_warmup_task"] = asyncio.create_task(_ensure_loaded())


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
    """Make the weights present, downloading on first use.

    No HF token and no license click are required: nvidia/LocateAnything-3B is
    a public, **ungated** repo, so a plain ``snapshot_download`` just works.
    This is the genuine one-click "enable → it downloads → it works" path
    (design §4). ``GROUNDING_MIRROR_URL`` is an optional override only for
    air-gapped installs that cannot reach huggingface.co.
    """
    dest = Path(settings.grounding_weights_dir)
    if dest.exists() and any(dest.iterdir()):
        return
    dest.mkdir(parents=True, exist_ok=True)

    mirror = settings.grounding_mirror_url
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

    # Default: direct, token-free pull from HuggingFace (the repo is ungated).
    # An HF token is optional and only raises anonymous rate limits.
    from huggingface_hub import snapshot_download

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None
    logger.info(
        "downloading grounding weights from HuggingFace (%s, no token required)",
        settings.grounding_model_id,
    )
    _STATE["downloading"] = True
    try:
        await asyncio.to_thread(
            snapshot_download,
            repo_id=settings.grounding_model_id,
            revision=settings.grounding_model_revision,
            local_dir=str(dest),
            token=token,
        )
    finally:
        _STATE["downloading"] = False


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
    from transformers import AutoModel, AutoProcessor, AutoTokenizer

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    # Let unsupported MPS ops fall back to CPU instead of erroring.
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    src = settings.grounding_weights_dir
    device = _pick_device()
    # The model's default text attention is `magi` (CUDA/Hopper only); off-CUDA
    # we force `sdpa`, which the model fully supports (MoonViT also auto-falls
    # back to sdpa without flash-attn).
    attn = None if device == "cuda" else "sdpa"
    logger.info("loading grounding model from %s (bf16, device=%s, attn=%s)", src, device, attn)
    tokenizer = AutoTokenizer.from_pretrained(src, trust_remote_code=True)
    processor = AutoProcessor.from_pretrained(src, trust_remote_code=True)
    kwargs = {"trust_remote_code": True, "torch_dtype": torch.bfloat16}
    if attn:
        kwargs["attn_implementation"] = attn
    model = AutoModel.from_pretrained(src, **kwargs).to(device).eval()
    _STATE["tokenizer"] = tokenizer
    _STATE["processor"] = processor
    _STATE["model"] = model
    _STATE["device"] = device


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
    """Generate the model's raw coordinate text via the LocateAnything recipe.

    Follows the model card's worker recipe (py_apply_chat_template +
    process_vision_info + the custom generate signature). The user's prompt is
    wrapped in the grounding instruction template. On Apple Silicon / CPU the
    `fast`/`hybrid` Parallel-Box-Decoding modes need CUDA kernels, so we clamp
    to `slow` (plain autoregressive), which produces the same <box> output.
    """
    import torch

    model = _STATE["model"]
    processor = _STATE["processor"]
    tokenizer = _STATE["tokenizer"]
    device = _STATE["device"] or "cpu"

    if device != "cuda":
        mode = "slow"

    question = f"Locate all the instances that matches the following description: {prompt}."
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text", "text": question},
    ]}]
    text = processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    images, videos = processor.process_vision_info(messages)
    inputs = processor(text=[text], images=images, videos=videos, return_tensors="pt").to(device)
    pixel_values = inputs["pixel_values"].to(torch.bfloat16)

    with torch.no_grad():
        resp = model.generate(
            pixel_values=pixel_values,
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            image_grid_hws=inputs.get("image_grid_hws", None),
            tokenizer=tokenizer,
            max_new_tokens=max_new_tokens,
            use_cache=True,
            generation_mode=mode,
            do_sample=False,
            verbose=False,
        )
    answer = resp[0] if isinstance(resp, tuple) else resp
    return answer if isinstance(answer, str) else str(answer)


def main() -> None:  # pragma: no cover - container entrypoint
    import uvicorn

    port = int(os.environ.get("GROUNDING_PORT", "8800"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
