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


_DRAFT_RULE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["description"],
    "properties": {
        "description": {
            "type": "string",
            "description": (
                "Plain-English description of the automation the user wants, "
                "e.g. 'alert me when a stranger is at the front door after 10pm'. "
                "No JSON, no field names."
            ),
        },
    },
}


def _summarize_rule(rule: dict) -> str:
    """A short human sentence describing a drafted rule for the confirm card."""
    tp = rule.get("trigger_pattern") or {}
    trig = tp.get("type", "activity")
    if tp.get("label"):
        trig = f"{tp['label']} detected"
    actions = [a.get("type") for a in (rule.get("actions") or []) if a.get("type")]
    act = ", ".join(actions) or "notify"
    conds = rule.get("conditions") or {}
    when = ""
    if conds.get("time_after") or conds.get("time_before"):
        when = f" between {conds.get('time_after','?')}-{conds.get('time_before','?')}"
    return f"{rule.get('name', 'Rule')}: on {trig}{when} → {act}"


def _rule_camera_ids(rule: dict) -> set[str]:
    """Every camera id a drafted rule references (trigger + conditions)."""
    out: set[str] = set()
    tp = rule.get("trigger_pattern") or {}
    if tp.get("camera_id"):
        out.add(str(tp["camera_id"]))
    conds = rule.get("conditions") or {}
    if conds.get("camera_id"):
        out.add(str(conds["camera_id"]))
    for c in conds.get("camera_ids") or []:
        out.add(str(c))
    return out


async def draft_rule(ctx: dict, *, description: str) -> dict:
    """Draft a real, ready-to-create rule from a description and hand it back
    as a confirm proposal (#284).

    Writes nothing: it translates the request into a validated rule and returns
    a ``client_action`` the UI renders as a Confirm card. The rule is only
    created when the user confirms (the client POSTs it to /api/rules). Scoped
    to the caller's cameras: a draft that references a camera they cannot see
    is refused.
    """
    from shared.camera_access import ALL, allowed_camera_ids

    db = ctx["db"]
    user = ctx.get("user")
    description = (description or "").strip()
    if not description:
        return {"ok": False, "error": "description must not be empty"}

    try:
        from services.api.routes.rules_nl import translate_rule

        out = await translate_rule(db, description)
    except Exception as exc:  # HTTPException (no provider / unparseable) or other
        detail = getattr(exc, "detail", None) or str(exc)
        return {
            "ok": False,
            "error": "could_not_draft",
            "message": f"I couldn't turn that into a rule: {detail}",
        }

    rule = out["rule"]

    # Permission: never draft a rule on a camera the caller cannot see.
    if user is not None:
        allowed = await allowed_camera_ids(user, db)
        if allowed is not ALL:
            import uuid as _uuid

            allowed_str = {str(c) for c in allowed}
            foreign = []
            for cid in _rule_camera_ids(rule):
                try:
                    _uuid.UUID(cid)
                except ValueError:
                    continue
                if cid not in allowed_str:
                    foreign.append(cid)
            if foreign:
                return {
                    "ok": False,
                    "error": "camera_out_of_scope",
                    "message": "That rule targets a camera you don't have access to.",
                }

    summary = _summarize_rule(rule)
    return {
        "ok": True,
        "rule": rule,
        "summary": summary,
        "notes": out.get("notes", []),
        "warnings": out.get("warnings", []),
        # The driver forwards client_action to the UI as a Confirm card; the
        # write happens only when the user confirms (client POSTs body).
        "client_action": {
            "kind": "create_rule",
            "method": "POST",
            "path": "/api/rules",
            "title": rule.get("name", "New rule"),
            "summary": summary,
            "warnings": out.get("warnings", []),
            "body": rule,
        },
        "message_for_user": (
            f"I've drafted this rule — {summary}. Review it below and press Confirm "
            "to create it (I won't create anything until you do)."
        ),
        "instructions": (
            "Tell the user you drafted the rule and they can confirm it below. "
            "Relay message_for_user; do not print the JSON or field names. If there "
            "are warnings, mention them briefly."
        ),
    }


_REMEMBER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fact"],
    "properties": {
        "fact": {
            "type": "string",
            "description": (
                "One plain-language fact about the household to remember, e.g. "
                "'the kids get home around 3:30pm on weekdays' or 'the grey "
                "sedan in the driveway is Dad's car'. A single sentence."
            ),
        },
    },
}


async def remember(ctx: dict, *, fact: str) -> dict:
    """Propose remembering a household fact (#286).

    Writes nothing: it returns a ``client_action`` the UI renders as a Confirm
    card, and the fact is stored (source="user", so the curator never rewrites
    it) only when the user confirms. Reuses the same confirm gate as draft_rule
    (#284)."""
    fact = (fact or "").strip()
    if not fact:
        return {"ok": False, "error": "fact must not be empty"}
    if len(fact) > 2000:
        fact = fact[:2000]
    return {
        "ok": True,
        "fact": fact,
        "client_action": {
            "kind": "remember_fact",
            "method": "POST",
            "path": "/api/household/facts",
            "title": "Remember this",
            "summary": fact,
            "body": {"text": fact, "kind": "note"},
        },
        "message_for_user": (
            f"Want me to remember that? “{fact}” — confirm below and I'll "
            "keep it in the household's memory (I won't save it until you do)."
        ),
        "instructions": (
            "Relay message_for_user; tell the user they can confirm below. Do not "
            "claim you already saved it — it saves only on confirm."
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


