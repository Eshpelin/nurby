"""Setup and diagnosis: rule schema, rule suggestions, camera tests, doctor.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

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
        "person": {
            "type": "string",
            "description": (
                "Attach the note to this person: exact display_name or person "
                "UUID. Only when the fact is about a specific person."
            ),
        },
        "vehicle": {
            "type": "string",
            "description": (
                "Attach the note to this vehicle: display_name, plate text, or "
                "vehicle UUID. Only when the fact is about a specific vehicle."
            ),
        },
        "camera": {
            "type": "string",
            "description": (
                "Attach the note to this camera: exact camera name or UUID. "
                "Only when the fact is about one specific camera."
            ),
        },
        "days": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": 6},
            "minItems": 1,
            "maxItems": 7,
            "description": (
                "When the statement is a recurring schedule: weekdays as ints, "
                "Monday=0 (so Thursday is 3). e.g. 'comes Tuesdays' -> [1]. "
                "Omit entirely for facts with no schedule."
            ),
        },
        "start_time": {
            "type": "string",
            "description": (
                "Schedule window start, local time 'HH:MM' (24h). Required "
                "when days is given; e.g. '9:00' or '21:30'."
            ),
        },
        "end_time": {
            "type": "string",
            "description": (
                "Schedule window end, local time 'HH:MM' (24h), after "
                "start_time, within the same day. e.g. '11:00'."
            ),
        },
    },
}


def _parse_hhmm(value: str | None) -> int | None:
    """'9:00' / '09:30' / '21:05' -> minutes since midnight, or None."""
    text = (value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


async def _resolve_remember_person(db, name: str) -> dict:
    """Resolve a person name/UUID for note attachment.

    Returns {"ok": True, "key": str, "label": str} or {"ok": False,
    "error": str}. Import lazily: the resolver lives with the
    relationship tools that share its disambiguation semantics.
    """
    from services.agent.tools.relationships import _resolve_subject

    desc = await _resolve_subject(name, db)
    if desc["type"] == "person":
        return {"ok": True, "key": str(desc["person_id"]), "label": desc.get("display") or desc["display_name"]}
    if desc["type"] == "disambiguation":
        names = ", ".join(c["display_name"] for c in desc["candidates"])
        return {"ok": False, "error": f"More than one person matches {name!r}: {names}. Ask which one."}
    return {"ok": False, "error": f"No person named {name!r} is in the people library"}


async def _resolve_remember_vehicle(db, name: str) -> dict:
    from shared.models import Vehicle

    needle = name.strip()
    rows = (
        await db.execute(
            select(Vehicle).where(
                func.lower(Vehicle.display_name).like(f"%{needle.lower()}%")
                | func.lower(func.coalesce(Vehicle.license_plate, "")).like(f"%{needle.lower()}%")
            )
        )
    ).scalars().all()
    if len(rows) > 1:
        names = ", ".join(v.display_name for v in rows)
        return {"ok": False, "error": f"More than one vehicle matches {name!r}: {names}. Ask which one."}
    if len(rows) == 1:
        return {"ok": True, "key": str(rows[0].id), "label": rows[0].display_name}
    return {"ok": False, "error": f"No vehicle matching {name!r} is in the vehicles library"}


async def _resolve_remember_camera(user, db, name: str) -> dict:
    """Resolve a camera name/UUID within the caller's ACL."""
    from services.agent.tools import _common

    raw = name.strip()
    try:
        resolved = uuid.UUID(raw)
    except ValueError:
        if user is None:
            return {"ok": False, "error": "camera must be a UUID"}
        allowed = await _common.accessible_camera_ids(user, db)
        result = await db.execute(
            select(Camera).where(func.lower(Camera.name) == raw.lower())
        )
        matches = [cam for cam in result.scalars().all() if cam.id in allowed]
        if not matches:
            return {"ok": False, "error": f"No accessible camera named {raw!r}"}
        if len(matches) > 1:
            return {"ok": False, "error": f"More than one camera is named {raw!r}; use its UUID."}
        resolved = matches[0].id
    cam = await db.get(Camera, resolved)
    if cam is None:
        return {"ok": False, "error": f"No camera with id {raw!r}"}
    return {"ok": True, "key": str(cam.id), "label": cam.name}


async def remember(
    ctx: dict,
    *,
    fact: str,
    person: str | None = None,
    vehicle: str | None = None,
    camera: str | None = None,
    days: list[int] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict:
    """Propose remembering a household note (#185).

    Writes nothing: it resolves the attachment and schedule, then returns a
    ``client_action`` the UI renders as a Confirm card. The note is stored
    (source="user", so the curator never rewrites it) only when the user
    confirms. A schedule-bearing card also arms alert suppression for that
    exact window — the card text says so, which makes the confirmation
    explicit; the effect stays visible and reversible on the note
    afterwards. Reuses the same confirm gate as draft_rule (#284)."""
    fact = (fact or "").strip()
    if not fact:
        return {"ok": False, "error": "fact must not be empty"}
    if len(fact) > 2000:
        fact = fact[:2000]
    db = ctx["db"]
    user = ctx.get("user")

    given = [name for name in (person, vehicle, camera) if name]
    if len(given) > 1:
        return {"ok": False, "error": "attach the note to one thing: a person, a vehicle, or a camera"}

    entity_kind = entity_key = entity_label = None
    if person:
        resolved = await _resolve_remember_person(db, person)
        if not resolved["ok"]:
            return resolved
        entity_kind, entity_key, entity_label = "person", resolved["key"], resolved["label"]
    elif vehicle:
        resolved = await _resolve_remember_vehicle(db, vehicle)
        if not resolved["ok"]:
            return resolved
        entity_kind, entity_key, entity_label = "vehicle", resolved["key"], resolved["label"]
    elif camera:
        resolved = await _resolve_remember_camera(user, db, camera)
        if not resolved["ok"]:
            return resolved
        entity_kind, entity_key, entity_label = "camera", resolved["key"], resolved["label"]
    else:
        entity_kind, entity_key, entity_label = "household", "household", "Household"

    # A schedule needs both ends and at least one weekday; anything
    # half-specified is a question back to the user, not a guess.
    schedule = None
    if days or start_time or end_time:
        start = _parse_hhmm(start_time)
        end = _parse_hhmm(end_time)
        if not days:
            return {"ok": False, "error": "a schedule needs days (weekday ints, Monday=0)"}
        if start is None or end is None:
            return {"ok": False, "error": "a schedule needs start_time and end_time as HH:MM"}
        if end <= start:
            return {"ok": False, "error": "end_time must be after start_time, within the same day"}
        schedule = {
            "days": sorted({int(d) for d in days if isinstance(d, int) and 0 <= int(d) <= 6}),
            "start_minute": start,
            "end_minute": end,
        }
        if not schedule["days"]:
            return {"ok": False, "error": "days must be weekday ints 0-6 (Monday=0)"}

    body = {"text": fact, "kind": "note"}
    if entity_kind != "household":
        body["entity_kind"] = entity_kind
        body["entity_key"] = entity_key
    if schedule:
        body["schedule"] = schedule
        # One confirmation, two stated effects: remember the note, and mute
        # matching alerts while the schedule holds. The message spells the
        # second effect out so the confirm is informed.
        body["suppress_alerts"] = True

    where = (
        "the household" if entity_kind == "household" else f"{entity_label} ({entity_kind})"
    )
    summary = fact
    will_mute = ""
    if schedule:
        from shared.fact_schedule import WEEKDAY_NAMES

        day_names = ", ".join(WEEKDAY_NAMES[d] for d in schedule["days"])
        window = (
            f"{schedule['start_minute'] // 60:02d}:{schedule['start_minute'] % 60:02d}"
            "-"
            f"{schedule['end_minute'] // 60:02d}:{schedule['end_minute'] % 60:02d}"
        )
        summary = f"{fact} — recurring {day_names} {window}"
        will_mute = (
            f" While that schedule holds, matching alerts for {where} will be "
            "muted (you can undo that on the note any time)."
        )
    return {
        "ok": True,
        "fact": fact,
        "entity": {"kind": entity_kind, "key": entity_key, "label": entity_label},
        "schedule": schedule,
        "client_action": {
            "kind": "remember_fact",
            "method": "POST",
            "path": "/api/household/facts",
            "title": "Remember this",
            "summary": summary,
            "body": body,
        },
        "message_for_user": (
            f"Want me to remember that? “{summary}” — I'd note it under {where}. "
            f"{will_mute}Confirm below and I'll keep it in the household's "
            "memory (I won't save it until you do)."
        ),
        "instructions": (
            "Relay message_for_user; tell the user they can confirm below. Do not "
            "claim you already saved it — it saves only on confirm. If the note "
            "carries a schedule, make sure they noticed that confirming also "
            "mutes matching alerts during the window."
        ),
    }


_TEST_CAMERA_CONNECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["camera_id"],
    "properties": {
        "camera_id": {
            "type": "string",
            "description": (
                "UUID or exact name of an existing camera. Human-readable "
                "camera names are accepted and resolved to the UUID."
            ),
        },
    },
}


async def test_camera_connection(ctx: dict, *, camera_id: str) -> dict:
    """Network probe of a camera's stream endpoint with a classified
    verdict (dns/refused/timeout/auth/not_found) and a fix hint."""
    import asyncio as _asyncio

    from services.api.camera_probe import ERROR_HINTS, parse_target, probe_rtsp_describe, probe_tcp

    db = ctx["db"]
    raw_camera_id = str(camera_id).strip()
    try:
        resolved_id = uuid.UUID(raw_camera_id)
    except ValueError:
        # The UI and household context present camera names to people. The
        # tool contract used to expose UUID-only input, which made a natural
        # request like "test Demo Camera" fail before the camera was even
        # looked up. Resolve exact names case-insensitively within the
        # caller's camera ACL and make ambiguity explicit.
        user = ctx.get("user")
        if user is None:
            return {"ok": False, "error": "camera_id must be a UUID or camera name"}
        from services.agent.tools import _common

        allowed = await _common.accessible_camera_ids(user, db)
        result = await db.execute(
            select(Camera).where(func.lower(Camera.name) == raw_camera_id.lower())
        )
        matches = [cam for cam in result.scalars().all() if cam.id in allowed]
        if not matches:
            return {"ok": False, "error": f"No accessible camera named {raw_camera_id!r}"}
        if len(matches) > 1:
            return {
                "ok": False,
                "error": f"More than one accessible camera is named {raw_camera_id!r}; use its UUID.",
            }
        resolved_id = matches[0].id

    cam = await db.get(Camera, resolved_id)
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
