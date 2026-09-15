"""Setup and diagnosis: rule schema, rule suggestions, camera tests, doctor.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid

from shared.models import (
    Camera,
)

# ── Setup / automation tools ────────────────────────────────────────


_GET_RULE_SCHEMA_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}


async def get_rule_schema(ctx: dict) -> dict:
    """The full rule vocabulary (trigger types, action types, condition
    fields, sequence shape). Use it to judge whether an automation the
    user wants is possible; never surface the raw field names."""
    from shared.rule_schema import build_schema

    return build_schema()


_SUGGEST_RULE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["description"],
    "properties": {
        "description": {
            "type": "string",
            "description": (
                "Plain-English description of the automation the user "
                "wants, e.g. 'notify me when a package is left at the "
                "front door'. No JSON, no field names."
            ),
        },
    },
}


async def suggest_rule(ctx: dict, *, description: str) -> dict:
    """Build a Rules-page deep link with the user's request pre-filled.

    The chat agent cannot create rules; rule creation happens on the
    Rules page where the user reviews the drafted rule before saving.
    This tool URL-encodes the description server-side so the model never
    has to construct (and potentially mangle) the link itself.
    """
    from urllib.parse import quote

    description = (description or "").strip()
    if not description:
        return {"ok": False, "error": "description must not be empty"}
    link = "/rules/new?describe=" + quote(description[:500])
    return {
        "ok": True,
        "link": link,
        "message_for_user": (
            "I can't create rules from this chat, but I can get you most "
            "of the way there: [Set up this rule](" + link + "). That "
            "opens the rule builder with your request already filled in, "
            "so you just review and save."
        ),
        "instructions": (
            "Give the user the message_for_user text (reword if you like, "
            "but keep the markdown link exactly as is). Never mention "
            "tools, functions, or field names."
        ),
    }


_TEST_CAMERA_CONNECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["camera_id"],
    "properties": {
        "camera_id": {"type": "string", "description": "UUID of an existing camera."},
    },
}


async def test_camera_connection(ctx: dict, *, camera_id: str) -> dict:
    """Network probe of a camera's stream endpoint with a classified
    verdict (dns/refused/timeout/auth/not_found) and a fix hint."""
    import asyncio as _asyncio

    from services.api.camera_probe import ERROR_HINTS, parse_target, probe_rtsp_describe, probe_tcp

    db = ctx["db"]
    try:
        cam = await db.get(Camera, uuid.UUID(camera_id))
    except ValueError:
        return {"ok": False, "error": "camera_id is not a UUID"}
    if cam is None:
        return {"ok": False, "error": "No camera with that id"}
    if cam.stream_type in ("file", "usb", "webcam", "browser_mic"):
        return {
            "ok": True,
            "skipped": True,
            "detail": f"{cam.stream_type} source has no network endpoint to probe",
        }
    host, port = parse_target(cam.stream_url or "")
    if not host:
        return {"ok": False, "error_code": "dns", "error": "Stream URL has no hostname"}
    tcp = await _asyncio.to_thread(probe_tcp, host, port, 4.0)
    if not tcp.get("ok"):
        code = tcp.get("error_code", "unknown")
        return {
            "ok": False,
            "error_code": code,
            "error": tcp.get("detail"),
            "hint": ERROR_HINTS.get(code),
        }
    result: dict = {"ok": True, "detail": f"{host}:{port} reachable"}
    if cam.stream_type == "rtsp":
        describe = await _asyncio.to_thread(probe_rtsp_describe, cam.stream_url, None, None, 5.0)
        if not describe.get("ok"):
            code = describe.get("error_code", "unknown")
            result = {
                "ok": False,
                "error_code": code,
                "error": describe.get("detail"),
                "hint": ERROR_HINTS.get(code),
            }
    return result


_RUN_DOCTOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}


async def run_doctor(ctx: dict) -> dict:
    """Full system health pass (db, redis, stream relay, every camera,
    every AI provider, smtp, disk) with per-check verdicts and hints."""
    from services.api.routes.doctor import run_doctor as doctor_endpoint

    checks = await doctor_endpoint(_current_user=ctx["user"], db=ctx["db"])
    return {"checks": [c.model_dump() for c in checks]}


