"""Natural-language rule generation.

POST /api/rules/generate turns "email me if someone loiters by the garage
after 10pm" into a RuleCreate-shaped dict: schema-grounded prompt, strict
JSON output, server-side validation with one repair retry, reference
warnings. It NEVER saves — the builder opens prefilled for review and the
user saves through the normal create path.
"""

import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.database import get_db
from shared.models import Camera, Device, Person, Provider, TelegramChannel, User
from shared.schemas import MentionRef, RuleCreate

router = APIRouter()
logger = logging.getLogger("nurby.api.rules_nl")


class GenerateRuleRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    provider_id: uuid.UUID | None = None
    # @-mentions from the composer: pre-resolved entity ids the model
    # must use verbatim. Verified server-side before prompt injection.
    mentions: list[MentionRef] = Field(default_factory=list, max_length=20)


class GenerateRuleResponse(BaseModel):
    rule: dict
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _compact_fields(fields: list[dict]) -> str:
    parts = []
    for f in fields:
        bit = f["name"]
        if f.get("required"):
            bit += "*"
        if f.get("enum"):
            bit += f"({'|'.join(str(v) for v in f['enum'])})"
        elif f.get("ref"):
            bit += f"({f['ref']} uuid)"
        parts.append(bit)
    return ", ".join(parts)


def build_system_prompt(
    schema: dict,
    cameras: list[tuple[str, str]],
    persons: list[tuple[str, str]],
    channels: list[tuple[str, str]],
    devices: list[tuple[str, str]] | None = None,
    mentions: list[dict] | None = None,
) -> str:
    """Compact, deterministic prompt: the full trigger/action/condition
    vocabulary plus the household's actual entities so names resolve to
    real UUIDs. Pure, for tests."""
    lines = [
        "You translate a user's plain-language automation wish into a Nurby rule as JSON.",
        "Output ONLY a JSON object: no prose, no code fences, no comments, no",
        "trailing commas. Keys:",
        '  name (short human title), enabled (true), trigger_pattern (object),',
        '  conditions (object or null), actions (array), cooldown_seconds (int, default 300),',
        '  severity ("alert" for urgent security things, "detection" otherwise).',
        "",
        "TRIGGER TYPES (pick exactly one; fields marked * are required):",
    ]
    for t in schema["triggers"]:
        lines.append(f"- {t['type']}: {t['description']} Fields: {_compact_fields(t['fields'])}")
    lines.append("")
    lines.append("ACTION TYPES:")
    for a in schema["actions"]:
        lines.append(f"- {a['type']}: {a['description']} Fields: {_compact_fields(a['fields'])}")
    lines.append("")
    lines.append("CONDITION FIELDS (all optional; omit conditions entirely if none apply):")
    lines.append("  " + _compact_fields(schema["conditions"]))
    lines.append("")
    lines.append(
        "Time windows: conditions.time_after/time_before use HH:MM 24h; an overnight "
        "window like 22:00→06:00 is expressed as time_after=\"22:00\", time_before=\"06:00\"."
    )
    lines.append("")
    lines.append("THIS HOUSEHOLD'S ENTITIES (use these exact UUIDs; never invent one):")
    lines.append("Cameras: " + (", ".join(f'"{n}" = {i}' for i, n in cameras) or "none"))
    lines.append("People: " + (", ".join(f'"{n}" = {i}' for i, n in persons) or "none"))
    lines.append(
        "Telegram channels: " + (", ".join(f'"{n}" = {i}' for i, n in channels) or "none")
    )
    lines.append(
        "Devices (physical alarms/relays; use the device action): "
        + (", ".join(f'"{n}" = {i}' for i, n in (devices or [])) or "none")
    )
    if mentions:
        lines.append("")
        lines.append(
            "USER-TAGGED ENTITIES (the user explicitly @-mentioned these; when the "
            "rule refers to them, use these exact UUIDs, never a different one):"
        )
        for m in mentions:
            lines.append(f"\"{m['name']}\" = {m['kind']} {m['id']}")
    lines.append("")
    lines.append(
        "Prefer the notify action when no Telegram channel exists and no email address "
        "was given. Scope to a camera via conditions.camera_ids when the user names a "
        "place and a matching camera exists; otherwise leave conditions null rather "
        "than guessing. Use sensible cooldowns (300s default; 60s for cries/alarms; "
        "600s for vehicles)."
    )
    lines.append("")
    lines.append("CHOOSING THE TRIGGER:")
    lines.append(
        '- A generic person ("a person", "someone", "somebody", "anybody", "a man", '
        '"a woman", "a kid") -> object_detected with label "person". This works on '
        "every camera with no extra setup. Always set the label on object_detected; "
        "omitting it fires on EVERY object (cars, cats, packages)."
    )
    lines.append(
        "- face_detected (any face, no identity) is rarely what users want; prefer "
        "face_recognized for a listed named person and object_detected for a generic "
        "person."
    )
    lines.append(
        "- face_recognized is ONLY for a specific named individual from the People "
        "list above; person_id must be one of those exact UUIDs. If the name is not "
        "in the list, or People is none, do NOT use face_recognized or face_detected; "
        'use object_detected with label "person".'
    )
    lines.append(
        '- face_unknown is only for "a stranger", "an unknown face", "someone we '
        'don\'t know".'
    )
    lines.append(
        "- loitering and line_cross need zone geometry drawn in the UI; only pick "
        'them when the user says "loiters", "hangs around", "stays too long" or '
        '"crosses the line". For plain arrivals, appearances or walk-ins use '
        "object_detected."
    )
    lines.append(
        "- Never output a placeholder value like \"person uuid here\"; omit an "
        "optional field entirely when you have no real UUID for it."
    )
    lines.append("")
    lines.append("EXAMPLES:")
    lines.append(
        'User: "notify me when a person shows up at the camera" -> '
        '{"name": "Person spotted", "enabled": true, '
        '"trigger_pattern": {"type": "object_detected", "label": "person"}, '
        '"conditions": null, "actions": [{"type": "notify", "message": "Person detected at {camera_name}", "severity": "info"}], '
        '"cooldown_seconds": 300, "severity": "detection"}'
    )
    lines.append(
        'User: "tell me when a package arrives" -> '
        '{"name": "Package arrives", "enabled": true, '
        '"trigger_pattern": {"type": "object_detected", "label": "package"}, '
        '"conditions": null, "actions": [{"type": "notify", "message": "Package detected at {camera_name}", "severity": "info"}], '
        '"cooldown_seconds": 300, "severity": "detection"}'
    )
    if persons:
        pid, pname = persons[0]
        lines.append(
            f'User: "tell me when {pname} gets home" -> '
            f'{{"name": "{pname} arrives", "enabled": true, '
            f'"trigger_pattern": {{"type": "face_recognized", "person_id": "{pid}"}}, '
            '"conditions": null, "actions": [{"type": "notify", "message": "'
            f'{pname} spotted at {{camera_name}}", "severity": "info"}}], '
            '"cooldown_seconds": 300, "severity": "detection"}'
        )
    lines.append(
        'User: "alert me if a stranger shows up after 10pm" -> '
        '{"name": "Stranger at night", "enabled": true, '
        '"trigger_pattern": {"type": "face_unknown"}, '
        '"conditions": {"time_after": "22:00", "time_before": "06:00"}, '
        '"actions": [{"type": "notify", "message": "Unknown face on {camera_name}", "severity": "warning"}], '
        '"cooldown_seconds": 300, "severity": "alert"}'
    )
    return "\n".join(lines)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_rule_json(text: str) -> dict:
    """Extract the JSON object from a model reply. Tolerates code fences
    and stray prose around the object. Raises ValueError when hopeless."""
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def coerce_impossible_face_trigger(
    rule: dict, persons: list[tuple[str, str]]
) -> list[str]:
    """Downgrade face triggers that can never fire to object detection.

    Small local models still sometimes map "a person shows up" to a face
    trigger. face_recognized cannot fire with an empty person library or a
    person_id that matches nobody (including hallucinated placeholders), so
    rewrite to object_detected label "person" and tell the user. Mutates
    ``rule``; returns notes. Pure, for tests."""
    tp = rule.get("trigger_pattern") or {}
    if tp.get("type") != "face_recognized":
        return []
    known = {pid for pid, _ in persons}
    pid = tp.get("person_id")
    if not persons:
        reason = "the person library is empty"
    elif pid is not None and str(pid) not in known:
        reason = f"person_id {str(pid)[:40]!r} matches nobody in the person library"
    else:
        return []
    rule["trigger_pattern"] = {"type": "object_detected", "label": "person"}
    return [
        'Changed the trigger from "Known face" to object detection of a person: '
        f"{reason}, so the rule could never fire. Add people under People and "
        "switch the trigger back if you meant a specific person."
    ]


async def _pick_provider(db: AsyncSession, provider_id: uuid.UUID | None) -> Provider:
    if provider_id is not None:
        provider = await db.get(Provider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        return provider
    result = await db.execute(select(Provider).where(Provider.active.is_(True)).limit(1))
    provider = result.scalars().first()
    if not provider:
        raise HTTPException(
            status_code=409,
            detail="No AI provider configured. Add one in Settings before generating rules.",
        )
    return provider


@router.post("/generate", response_model=GenerateRuleResponse)
async def generate_rule(
    body: GenerateRuleRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.agent.llm import llm_call
    from services.api.routes.rules import _stale_rule_refs
    from shared.rule_schema import build_schema

    provider = await _pick_provider(db, body.provider_id)
    model = provider.default_model
    if not model:
        raise HTTPException(status_code=409, detail="The provider has no default model set.")

    cameras = [
        (str(i), n) for i, n in (await db.execute(select(Camera.id, Camera.name))).all()
    ]
    persons = [
        (str(i), n)
        for i, n in (await db.execute(select(Person.id, Person.display_name))).all()
    ]
    channels = [
        (str(i), n or "Telegram")
        for i, n in (
            await db.execute(
                select(TelegramChannel.id, TelegramChannel.label).where(
                    TelegramChannel.enabled.is_(True)
                )
            )
        ).all()
    ]
    devices = [
        (str(i), n)
        for i, n in (
            await db.execute(select(Device.id, Device.name).where(Device.enabled.is_(True)))
        ).all()
    ]

    from services.api.routes.mentions import verify_mentions

    verified_mentions = await verify_mentions(db, body.mentions)

    system_prompt = build_system_prompt(
        build_schema(), cameras, persons, channels, devices, verified_mentions
    )
    messages = [{"role": "user", "content": body.prompt}]
    notes: list[str] = []

    candidate: dict | None = None
    last_error = ""
    raw_text = ""
    for attempt in range(2):
        resp = await llm_call(provider, model, system_prompt, messages, tools=[], max_tokens=1500)
        raw_text = resp.text or ""
        try:
            parsed = parse_rule_json(raw_text)
            # Drop keys RuleCreate doesn't know instead of failing on them.
            allowed = set(RuleCreate.model_fields)
            extra = set(parsed) - allowed
            if extra:
                notes.append(f"Dropped unknown keys from the model output: {sorted(extra)}")
            candidate = RuleCreate(**{k: v for k, v in parsed.items() if k in allowed}).model_dump()
            break
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:800]
            if attempt == 0:
                # Feed the failure back once; models usually repair from it.
                messages.append({"role": "assistant", "content": raw_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That output failed validation:\n"
                            f"{last_error}\n"
                            "Return ONLY the corrected JSON object."
                        ),
                    }
                )
                notes.append("First attempt failed validation; retried with the error.")

    if candidate is None:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Could not generate a valid rule from that description.",
                "error": last_error,
                "raw": raw_text[:2000],
            },
        )

    notes.extend(coerce_impossible_face_trigger(candidate, persons))

    warnings = await _stale_rule_refs(
        db, candidate.get("trigger_pattern"), candidate.get("conditions"), candidate.get("actions")
    )
    return GenerateRuleResponse(rule=candidate, notes=notes, warnings=warnings)
