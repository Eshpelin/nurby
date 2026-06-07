"""Native-audio conversation analysis (n2.0 scaffold).

Feeds a finalized conversation's audio clip to an audio-capable model to
extract what the audio reveals beyond the whisper transcript. speaker
count, tone, non-verbal cues, and a grounded gist. Design and the runtime
gap are documented in docs/native-audio-conversation-design.md.

This is a no-op unless a ``supports_audio`` provider is configured. when
none is, the conversation keeps its whisper-text summary and nothing
regresses. A concrete Gemini (cloud) path is implemented. local gemma3n
waits on an ollama audio API, see the design doc.
"""

from __future__ import annotations

import base64
import json
import logging
import os

logger = logging.getLogger("nurby.perception.audio_conversation")

_TONES = {"calm", "tense", "argument", "distressed", "playful", "unclear"}

_ANALYZER_PROMPT = (
    "You are given the AUDIO of a short conversation captured by a home "
    "security camera, plus the rough TRANSCRIPT the speech recognizer "
    "produced. Listen to the audio and reply with a compact JSON object: "
    '{"speaker_count": int, "tone": one of '
    '["calm","tense","argument","distressed","playful","unclear"], '
    '"non_verbal": [strings like "laughter","crying","raised-voice"], '
    '"gist": "one factual sentence about what is happening, grounded in how '
    'it sounds"}. Add only what the audio reveals beyond the words. No '
    "preamble, JSON only."
)


def provider_supports_audio(provider) -> bool:
    """Whether a provider can ingest audio input.

    Cloud Gemini accepts audio. an explicit ``supports_audio`` attribute (a
    future column) wins if present. Ollama is excluded. its generate API
    takes images only, not audio (see the design doc's runtime gap).
    """
    if provider is None:
        return False
    if getattr(provider, "supports_audio", None):
        return True
    kind = getattr(provider, "kind", "")
    model = (getattr(provider, "default_model", "") or "").lower()
    if kind == "google" and "gemini" in model:
        return True
    if kind == "openai" and "audio" in model:
        return True
    return False


async def analyze_conversation_audio(clip_path: str | None, transcript_text: str,
                                     provider) -> dict | None:
    """Return audio-derived conversation fields, or None when unavailable.

    None is the normal path until an audio-capable provider is configured.
    Callers must treat None as "keep the existing text summary".
    """
    if not clip_path or not os.path.exists(clip_path):
        return None
    if not provider_supports_audio(provider):
        return None
    try:
        if getattr(provider, "kind", "") == "google":
            raw = await _gemini_audio(clip_path, transcript_text, provider)
        else:
            return None
    except Exception:
        logger.debug("audio conversation analysis failed", exc_info=True)
        return None
    return _parse(raw)


async def _gemini_audio(clip_path: str, transcript_text: str, provider) -> str | None:
    """Call Gemini with inline audio. Requires provider.api_key."""
    import httpx

    if not provider.api_key:
        return None
    with open(clip_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()
    mime = "audio/ogg" if clip_path.endswith(".opus") else "audio/mp4"
    model = provider.default_model or "gemini-2.0-flash"
    url = (f"{provider.base_url.rstrip('/')}/v1beta/models/{model}:generateContent"
           f"?key={provider.api_key}")
    body = {
        "contents": [{
            "parts": [
                {"text": _ANALYZER_PROMPT + f"\n\nTRANSCRIPT:\n{transcript_text[:2000]}"},
                {"inline_data": {"mime_type": mime, "data": audio_b64}},
            ]
        }],
        "generationConfig": {"maxOutputTokens": 200, "temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=body)
    if r.status_code != 200:
        logger.debug("gemini audio %s. %s", r.status_code, r.text[:200])
        return None
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return None


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    text = raw.strip()
    # tolerate code fences / preamble around the JSON
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except Exception:
        return None
    tone = str(obj.get("tone", "")).lower()
    nv = obj.get("non_verbal")
    sc = obj.get("speaker_count")
    return {
        "speaker_count": int(sc) if isinstance(sc, (int, float)) else None,
        "tone": tone if tone in _TONES else None,
        "non_verbal": [str(x) for x in nv][:8] if isinstance(nv, list) else None,
        "gist": (str(obj.get("gist")) or None) if obj.get("gist") else None,
    }
