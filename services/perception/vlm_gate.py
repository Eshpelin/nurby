"""
CLIP zero-shot pre-classifier gate for the VLM enqueue path.

The motion detector + pHash dedupe already cull obvious cases (idle
camera, identical scene). What's still left for outdoor cameras is
"scene changed but nothing of interest happened" — wind moving leaves,
a flag waving, sun shadows shifting. The VLM would describe these as
"empty backyard" at 15 seconds per frame; that's pure waste.

This module runs a tiny CLIP zero-shot classifier against a curated
list of "interesting" vs "boring" prompts. If the boring class wins by
a margin, we skip the VLM enqueue entirely.

Cost vs benefit.
  - First load. ~150 MB model download + ~3 s warmup.
  - Per-frame inference. ~30 ms CPU, ~5 ms GPU. Compared to a 15 s
    Ollama VLM call, even a 50% skip rate pays for itself fast.

Graceful degrade. If open_clip isn't installed, the gate disables
itself and the pipeline keeps behaving as it does today (allow all).
Same on any inference error. We never starve the VLM pipeline on a
classifier hiccup.

Configurable via AppSettings.
  vlm_gate_enabled                bool, default true
  vlm_gate_model                  string, default "ViT-B-32" / "laion2b_s34b_b79k"
  vlm_gate_margin                 float, default 0.05 (boring wins by 5%+)
  vlm_gate_min_interesting_score  float, default 0.20 (absolute floor)
  vlm_gate_interesting_prompts    list[str]
  vlm_gate_boring_prompts         list[str]
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger("nurby.perception.vlm_gate")


DEFAULT_INTERESTING_PROMPTS = [
    "a photo of a person",
    "a photo of a vehicle",
    "a photo of a delivery package",
    "a photo of an animal",
    "a photo of someone walking",
    "a photo of a face",
    "a photo of activity at a doorway",
]

DEFAULT_BORING_PROMPTS = [
    "a photo of an empty room",
    "a photo of an empty street",
    "a photo of an empty yard",
    "a photo of trees moving in the wind",
    "a photo of leaves on the ground",
    "a photo of a parked vehicle with nothing else",
    "a photo of a closed door with nothing happening",
]


@dataclass
class GateDecision:
    allow: bool
    interesting_score: float
    boring_score: float
    interesting_label: str
    boring_label: str
    reason: str  # "interesting", "boring", "below_floor", "disabled", "error"


class CLIPGate:
    """Lazy-loaded open_clip zero-shot classifier."""

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "laion2b_s34b_b79k",
    ):
        self._model_name = model_name
        self._pretrained = pretrained
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._device = "cpu"
        self._load_failed = False
        # Cached text features so we don't re-encode the prompts every
        # frame. Keyed by (tuple(prompts), kind).
        self._text_cache: dict[tuple, "object"] = {}

    # ── public API ────────────────────────────────────────────────────

    async def classify(
        self,
        frame_bgr: np.ndarray,
        interesting_prompts: list[str],
        boring_prompts: list[str],
        margin: float = 0.05,
        min_interesting_score: float = 0.20,
    ) -> GateDecision:
        """Return a decision for whether ``frame_bgr`` should be VLM'd."""
        if self._load_failed:
            return GateDecision(
                allow=True, interesting_score=0.0, boring_score=0.0,
                interesting_label="", boring_label="", reason="disabled",
            )
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None,
                self._classify_sync,
                frame_bgr, interesting_prompts, boring_prompts,
                margin, min_interesting_score,
            )
        except Exception:
            logger.exception("CLIP gate inference failed; allowing")
            return GateDecision(
                allow=True, interesting_score=0.0, boring_score=0.0,
                interesting_label="", boring_label="", reason="error",
            )

    async def embed_image(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        """Return the L2-normalized CLIP image embedding for a crop, or None
        if CLIP is unavailable. Reused for plateless vehicle appearance re-id.
        """
        if self._load_failed:
            return None
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._embed_image_sync, frame_bgr,
            )
        except Exception:
            logger.debug("CLIP image embed failed", exc_info=True)
            return None

    def _embed_image_sync(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        if not self._load():
            return None
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        with torch.no_grad():
            image = self._preprocess(pil).unsqueeze(0).to(self._device)
            feats = self._model.encode_image(image)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.squeeze(0).cpu().numpy()

    # ── internals ─────────────────────────────────────────────────────

    def _load(self) -> bool:
        if self._model is not None:
            return True
        if self._load_failed:
            return False
        try:
            import open_clip  # type: ignore
            import torch  # type: ignore
        except ImportError:
            logger.warning(
                "open_clip / torch not installed; CLIP gate disabled. "
                "VLM gate falls open. install open_clip_torch to enable."
            )
            self._load_failed = True
            return False
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                self._model_name, pretrained=self._pretrained,
            )
            tokenizer = open_clip.get_tokenizer(self._model_name)
            if torch.cuda.is_available():
                self._device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                self._device = "mps"
            model = model.to(self._device)
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = tokenizer
            logger.info("CLIP gate loaded on %s (%s/%s)", self._device, self._model_name, self._pretrained)
            return True
        except Exception:
            logger.exception("CLIP gate model load failed; gate disabled")
            self._load_failed = True
            return False

    def _encode_prompts(self, prompts: tuple, kind: str):
        """Return the cached text feature tensor for ``prompts``."""
        key = (prompts, kind)
        cached = self._text_cache.get(key)
        if cached is not None:
            return cached
        import torch  # type: ignore

        with torch.no_grad():
            tokens = self._tokenizer(list(prompts)).to(self._device)
            feats = self._model.encode_text(tokens)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        self._text_cache[key] = feats
        return feats

    def _classify_sync(
        self,
        frame_bgr: np.ndarray,
        interesting_prompts: list[str],
        boring_prompts: list[str],
        margin: float,
        min_interesting_score: float,
    ) -> GateDecision:
        if not self._load():
            return GateDecision(
                allow=True, interesting_score=0.0, boring_score=0.0,
                interesting_label="", boring_label="", reason="disabled",
            )
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        with torch.no_grad():
            image = self._preprocess(pil).unsqueeze(0).to(self._device)
            image_feats = self._model.encode_image(image)
            image_feats = image_feats / image_feats.norm(dim=-1, keepdim=True)

            int_feats = self._encode_prompts(tuple(interesting_prompts), "int")
            bor_feats = self._encode_prompts(tuple(boring_prompts), "bor")

            int_sims = (image_feats @ int_feats.T).squeeze(0).cpu().numpy()
            bor_sims = (image_feats @ bor_feats.T).squeeze(0).cpu().numpy()

        int_top = int(int_sims.argmax())
        bor_top = int(bor_sims.argmax())
        int_score = float(int_sims[int_top])
        bor_score = float(bor_sims[bor_top])
        int_label = interesting_prompts[int_top]
        bor_label = boring_prompts[bor_top]

        # Decision rule:
        #  - Hard floor on interesting score. below 0.2 = no class is
        #    confidently present, skip.
        #  - Otherwise compare. if boring wins by `margin`, skip.
        if int_score < min_interesting_score:
            return GateDecision(
                allow=False, interesting_score=int_score, boring_score=bor_score,
                interesting_label=int_label, boring_label=bor_label, reason="below_floor",
            )
        if bor_score - int_score > margin:
            return GateDecision(
                allow=False, interesting_score=int_score, boring_score=bor_score,
                interesting_label=int_label, boring_label=bor_label, reason="boring",
            )
        return GateDecision(
            allow=True, interesting_score=int_score, boring_score=bor_score,
            interesting_label=int_label, boring_label=bor_label, reason="interesting",
        )


# Module-level singleton so the model is loaded once per process.
_gate: CLIPGate | None = None


def get_gate() -> CLIPGate:
    global _gate
    if _gate is None:
        _gate = CLIPGate()
    return _gate


async def maybe_skip_via_gate(
    frame_bgr: np.ndarray,
    *,
    enabled: bool,
    interesting_prompts: list[str] | None,
    boring_prompts: list[str] | None,
    margin: float,
    min_interesting_score: float,
) -> GateDecision:
    """Convenience for callers. Returns a GateDecision; respect .allow."""
    if not enabled:
        return GateDecision(
            allow=True, interesting_score=0.0, boring_score=0.0,
            interesting_label="", boring_label="", reason="disabled",
        )
    interesting = interesting_prompts or DEFAULT_INTERESTING_PROMPTS
    boring = boring_prompts or DEFAULT_BORING_PROMPTS
    return await get_gate().classify(
        frame_bgr, interesting, boring,
        margin=margin, min_interesting_score=min_interesting_score,
    )


__all__ = [
    "CLIPGate",
    "GateDecision",
    "DEFAULT_INTERESTING_PROMPTS",
    "DEFAULT_BORING_PROMPTS",
    "get_gate",
    "maybe_skip_via_gate",
]
