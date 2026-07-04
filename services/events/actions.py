"""
Action executors for rule engine.

Each action type has its own executor. Actions receive observation
data, the matched rule, and the stored event ID.

Supported action types.
    webhook     POST to a URL with optional custom payload template and headers
    api_call    Full HTTP call with method, auth (Bearer/API key/Basic), custom payload
    broadcast   Push to WebSocket clients with optional custom payload
    notify      Store notification + broadcast via WebSocket
    email       Send email via SMTP with template subject and body
    vlm_call    Ask a VLM provider a question, optionally structured JSON output
    telegram    Send a chat message via a paired Telegram bot channel.
                Phase 1 is text only. Action shape.
                    {"type": "telegram", "channel_id": uuid, "template": str,
                     "include_thumbnail": bool, "silent": bool}
                Template variables available. {rule_name}, {camera_name},
                {timestamp_local}, {vlm_description}, {detections_summary},
                {observation_id}, {event_id}. Both {{var}} and {var}
                shorthand are accepted for parity with the notify action.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from services.events.templates import (
    ConditionError,
    render,
    safe_eval_condition,
)
from shared.database import async_session
from shared.models import Event, Notification, Provider, WebhookSubscription

logger = logging.getLogger("nurby.events.actions")

# Outbound delivery defaults. retries with exponential backoff.
_RETRY_BACKOFF = (0.5, 1.5, 3.0)


async def dispatch_subscriptions(observation_data: dict, rule, event_id) -> None:
    """Fan a fired event out to every active webhook subscription whose
    filters match. Independent of per-rule webhook actions. Best-effort.
    a failed delivery is recorded on the subscription, never raised."""
    try:
        async with async_session() as db:
            subs = (
                await db.execute(
                    select(WebhookSubscription).where(
                        WebhookSubscription.active.is_(True)
                    )
                )
            ).scalars().all()
    except Exception:
        logger.exception("failed to load webhook subscriptions")
        return
    if not subs:
        return

    ctx = _build_template_context(observation_data, rule, event_id)
    payload = _build_default_payload(ctx)
    cam = observation_data.get("camera_id")
    rid = str(getattr(rule, "id", "")) if rule is not None else ""

    for sub in subs:
        if sub.rule_ids and rid not in [str(r) for r in sub.rule_ids]:
            continue
        if sub.camera_ids and cam not in [str(c) for c in sub.camera_ids]:
            continue
        ok, detail = await deliver_signed(
            "POST", sub.url, payload, secret=sub.secret or None,
        )
        try:
            async with async_session() as db2:
                row = await db2.get(WebhookSubscription, sub.id)
                if row is not None:
                    row.last_delivery_at = datetime.now(timezone.utc)
                    row.last_status = (("ok " if ok else "fail ") + detail)[:120]
                    await db2.commit()
        except Exception:
            logger.exception("failed to record subscription delivery")


def sign_body(body: bytes, secret: str) -> str:
    """HMAC-SHA256 signature of a raw body. Receivers recompute this
    over the bytes they receive and compare to verify authenticity."""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


async def deliver_signed(
    method: str,
    url: str,
    payload,
    *,
    headers: dict | None = None,
    secret: str | None = None,
    params: dict | None = None,
    timeout: float = 10.0,
    attempts: int = 3,
) -> tuple[bool, str]:
    """Deliver a JSON payload with optional HMAC signing and retries.

    Signs the exact serialized bytes so the receiver can verify. Retries
    on timeout, connection error, and 5xx with exponential backoff.
    Returns (ok, detail). 4xx is not retried (caller misconfig).
    """
    from shared.netpolicy import webhook_target_rejection

    rejection = await webhook_target_rejection(url)
    if rejection:
        return (False, f"target refused: {rejection}")

    headers = dict(headers or {})
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers.setdefault("Content-Type", "application/json")
    if secret:
        headers["X-Nurby-Signature"] = sign_body(body, secret)
    last = "no attempt made"
    async with httpx.AsyncClient() as client:
        for i in range(max(1, attempts)):
            try:
                resp = await client.request(
                    method, url, content=body, headers=headers,
                    params=params, timeout=timeout,
                )
                if resp.status_code < 500:
                    return (resp.status_code < 400, f"status {resp.status_code}")
                last = f"status {resp.status_code}"
            except httpx.TimeoutException:
                last = f"timeout connecting to {url}"
            except httpx.RequestError as exc:
                last = str(exc)
            if i < attempts - 1:
                await asyncio.sleep(_RETRY_BACKOFF[min(i, len(_RETRY_BACKOFF) - 1)])
    return (False, last)

# Legacy single-segment template pattern kept for default payload builder.
_TEMPLATE_VAR = re.compile(r"\{\{(\w+)\}\}")

DEFAULT_VLM_SYSTEM = (
    "You are a security camera AI assistant. Describe what you see in this camera frame "
    "in 1-2 concise sentences. Focus on people, vehicles, animals, and any unusual activity."
)


def _build_template_context(
    observation_data: dict,
    rule,
    event_id: uuid.UUID,
) -> dict:
    """Build nested context dict available for template interpolation."""
    vars_bag = observation_data.get("vars") or {}
    # Resolve {event_url} from the configured public base URL. When
    # unset, downstream template renderers see an empty string and
    # the Telegram action editor surfaces a one-line warning.
    from shared.config import settings as _settings
    _base = (_settings.public_base_url or "").rstrip("/")
    event_url = f"{_base}/rules?event={event_id}" if _base else ""
    ctx = {
        "event_id": str(event_id),
        "event_url": event_url,
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "camera_id": observation_data.get("camera_id", ""),
        "camera_name": observation_data.get("camera_name") or observation_data.get("camera_id", ""),
        "timestamp": observation_data.get("timestamp", ""),
        "timestamp_local": observation_data.get("timestamp_local")
        or _localize_timestamp(
            observation_data.get("timestamp"),
            observation_data.get("camera_timezone"),
        ),
        "motion_score": observation_data.get("motion_score", 0),
        "object_detections": observation_data.get("object_detections"),
        "person_detections": observation_data.get("person_detections"),
        "objects": observation_data.get("object_detections"),
        "faces": observation_data.get("person_detections"),
        "description": observation_data.get("vlm_description", ""),
        "vlm_description": observation_data.get("vlm_description", ""),
        "detections_summary": _summarize_detections(observation_data),
        "confidence": observation_data.get("confidence"),
        "observation_id": observation_data.get("observation_id", ""),
        "recording_id": observation_data.get("recording_id") or "",
        "recording_url": observation_data.get("recording_url") or "",
        "thumbnail_url": observation_data.get("thumbnail_url") or observation_data.get("thumbnail_path", ""),
        "thumbnail_path": observation_data.get("thumbnail_path", ""),
        "vars": vars_bag,
        "defaults": {"system": DEFAULT_VLM_SYSTEM},
    }
    return ctx


def _localize_timestamp(ts_value, tz_name: str | None) -> str:
    """Render an observation timestamp in the camera's timezone.

    Falls back to the raw value if parsing fails so templates never
    silently produce empty strings.
    """
    if not ts_value:
        return ""
    try:
        from datetime import datetime
        if isinstance(ts_value, datetime):
            dt = ts_value
        else:
            dt = datetime.fromisoformat(str(ts_value).replace("Z", "+00:00"))
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                dt = dt.astimezone(ZoneInfo(tz_name))
            except Exception:
                pass
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    except Exception:
        return str(ts_value)


def _summarize_detections(observation_data: dict) -> str:
    """Compact, human-friendly summary of what was seen. Used by the
    Telegram and email templates so users don't have to format
    detection dicts themselves."""
    pieces: list[str] = []
    objs = observation_data.get("object_detections") or {}
    olist = objs.get("objects") if isinstance(objs, dict) else None
    if olist:
        counts: dict[str, int] = {}
        for det in olist:
            label = str(det.get("label") or "object")
            counts[label] = counts.get(label, 0) + 1
        pieces.extend(f"{n} {label}" for label, n in sorted(counts.items()))
    faces = observation_data.get("person_detections") or {}
    if isinstance(faces, dict) and faces.get("count"):
        pieces.append(f"{faces['count']} face(s)")
    return ", ".join(pieces) if pieces else "no detections"


def _render_template(template, context: dict):
    """Legacy wrapper that now routes to the shared template engine."""
    return render(template, context, strict=False)


def _build_default_payload(context: dict) -> dict:
    return {
        "event_id": context["event_id"],
        "rule_id": context["rule_id"],
        "rule_name": context["rule_name"],
        "camera_id": context["camera_id"],
        "camera_name": context.get("camera_name", ""),
        "timestamp": context["timestamp"],
        "motion_score": context["motion_score"],
        "object_detections": context["object_detections"],
        "person_detections": context["person_detections"],
        "vlm_description": context["vlm_description"],
        "observation_id": context.get("observation_id", ""),
        "recording_id": context.get("recording_id", ""),
        "recording_url": context.get("recording_url", ""),
        "thumbnail_url": context.get("thumbnail_url", ""),
        "event_url": context.get("event_url", ""),
    }


def _apply_auth(headers: dict, auth_config: dict | None):
    if not auth_config:
        return
    auth_type = auth_config.get("type", "")
    if auth_type == "bearer":
        token = auth_config.get("token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        header_name = auth_config.get("header", "X-API-Key")
        key = auth_config.get("key", "")
        if key:
            headers[header_name] = key
    elif auth_type == "basic":
        username = auth_config.get("username", "")
        password = auth_config.get("password", "")
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"


async def _update_event_status(
    event_id: uuid.UUID,
    action_type: str,
    status: str,
    error: str | None = None,
):
    try:
        async with async_session() as db:
            event = await db.get(Event, event_id)
            if event:
                event.action_type = action_type
                event.action_status = status
                event.action_error = error
                await db.commit()
    except Exception:
        logger.exception("Failed to update event %s status", event_id)


def _check_condition(action: dict, ctx: dict, rule_name: str) -> bool:
    expr = action.get("condition")
    if not expr:
        return True
    try:
        result = safe_eval_condition(expr, ctx)
    except ConditionError as exc:
        logger.warning("Bad condition in rule '%s'. %s", rule_name, exc)
        return False
    if not result:
        logger.debug("Rule '%s' action condition false. skipping", rule_name)
    return bool(result)


async def execute_action(
    action: dict,
    observation_data: dict,
    rule,
    event_id: uuid.UUID,
):
    """Dispatch action to correct executor based on type."""
    action_type = action.get("type")

    ctx = _build_template_context(observation_data, rule, event_id)
    if not _check_condition(action, ctx, rule.name):
        return

    if action_type == "webhook":
        await _execute_webhook(action, observation_data, rule, event_id, ctx)
    elif action_type == "api_call":
        await _execute_api_call(action, observation_data, rule, event_id, ctx)
    elif action_type == "broadcast":
        await _execute_broadcast(action, observation_data, rule, event_id, ctx)
    elif action_type == "notify":
        await _execute_notify(action, observation_data, rule, event_id, ctx)
    elif action_type == "email":
        await _execute_email(action, observation_data, rule, event_id, ctx)
    elif action_type == "vlm_call":
        await _execute_vlm_call(action, observation_data, rule, event_id, ctx)
    elif action_type == "telegram":
        await _execute_telegram(action, observation_data, rule, event_id, ctx)
    elif action_type == "verify":
        await _execute_verify(action, observation_data, rule, event_id, ctx)
    elif action_type == "locate":
        await _execute_locate(action, observation_data, rule, event_id, ctx)
    elif action_type == "device":
        await _execute_device(action, observation_data, rule, event_id, ctx)
    else:
        logger.warning("Unknown action type '%s' in rule '%s'", action_type, rule.name)
        await _update_event_status(event_id, action_type or "unknown", "failed", f"Unknown action type '{action_type}'")


def render_device_payload(template: dict, ctx: dict) -> dict:
    """Render a device payload template with BOTH `{var}` and `{{var}}`
    token styles.

    Device preset payloads (integrations/devices/catalog.py) use the
    single-brace shorthand users learned from Notification/Telegram
    templates; the shared engine only speaks double-brace. Run the
    normal renderer first (it consumes {{token}}), then expand the
    remaining single-brace tokens for scalar context keys. Also used by
    the device test-fire endpoint so a manual test exercises the exact
    fire-time path."""

    def expand(value):
        if isinstance(value, dict):
            return {k: expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(v) for v in value]
        if isinstance(value, str):
            out = value
            for key, val in ctx.items():
                token = "{" + key + "}"
                if token in out and not isinstance(val, (dict, list)):
                    out = out.replace(token, _stringify_ctx(val))
            return out
        return value

    return expand(render(template, ctx, strict=False))


async def _execute_device(action, observation_data, rule, event_id, ctx):
    """Fire a registered physical device (Device row). Endpoint, secret,
    timeout and payload template resolve from the row at fire time, so
    device edits retarget every rule that references it."""
    from shared.camera_secrets import unseal
    from shared.database import async_session
    from shared.models import Device

    raw_id = action.get("device_id")
    try:
        device_uuid = uuid.UUID(str(raw_id))
    except (ValueError, TypeError):
        await _update_event_status(event_id, "device", "failed", "Missing or invalid 'device_id'")
        return

    async with async_session() as db:
        device = await db.get(Device, device_uuid)
        if device is None:
            await _update_event_status(event_id, "device", "failed", "Device not found")
            return
        if not device.enabled:
            await _update_event_status(event_id, "device", "failed", "Device is disabled")
            return
        endpoint_url = device.endpoint_url
        secret = unseal(device.secret)
        timeout = float(device.timeout_seconds or 5)
        payload_template = device.payload_template

    payload = (
        render_device_payload(payload_template, ctx)
        if payload_template
        else _build_default_payload(ctx)
    )
    extras = action.get("extras")
    if isinstance(extras, dict):
        payload.update(render_device_payload(extras, ctx))

    ok, detail = await deliver_signed(
        "POST", endpoint_url, payload, secret=secret, timeout=timeout
    )
    if ok:
        await _update_event_status(event_id, "device", "success")
    else:
        await _update_event_status(event_id, "device", "failed", detail)


async def _execute_webhook(action, observation_data, rule, event_id, ctx):
    url_tpl = action.get("url")
    if not url_tpl:
        await _update_event_status(event_id, "webhook", "failed", "Missing 'url' in webhook action")
        return
    url = render(url_tpl, ctx)

    payload_template = action.get("payload_template")
    if payload_template:
        payload = render(payload_template, ctx)
    else:
        payload = _build_default_payload(ctx)

    headers = render(dict(action.get("headers", {})), ctx)
    _apply_auth(headers, action.get("auth"))
    timeout = action.get("timeout", 10)
    secret = action.get("secret") or None

    ok, detail = await deliver_signed(
        "POST", url, payload, headers=headers, secret=secret, timeout=timeout,
    )
    if ok:
        logger.info("Webhook fired for rule '%s' -> %s (%s)", rule.name, url, detail)
        await _update_event_status(event_id, "webhook", "success")
    else:
        await _update_event_status(event_id, "webhook", "failed", detail)


async def _execute_api_call(action, observation_data, rule, event_id, ctx):
    url_tpl = action.get("url")
    if not url_tpl:
        await _update_event_status(event_id, "api_call", "failed", "Missing 'url' in api_call action")
        return
    url = render(url_tpl, ctx)
    method = render(action.get("method", "POST"), ctx).upper()

    payload = None
    payload_template = action.get("payload_template")
    if payload_template:
        payload = render(payload_template, ctx)
    elif method in ("POST", "PUT", "PATCH"):
        payload = _build_default_payload(ctx)

    headers = render(dict(action.get("headers", {})), ctx)
    _apply_auth(headers, action.get("auth"))

    query_params = action.get("query_params")
    if query_params:
        query_params = render(query_params, ctx)

    timeout = action.get("timeout", 10)
    secret = action.get("secret") or None

    if payload is None:
        # No body. fall back to a single plain request (nothing to sign).
        from shared.netpolicy import webhook_target_rejection

        rejection = await webhook_target_rejection(url)
        if rejection:
            await _update_event_status(
                event_id, "api_call", "failed", f"target refused: {rejection}"
            )
            return
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.request(
                    method, url, headers=headers, params=query_params, timeout=timeout,
                )
                logger.info(
                    "API call fired for rule '%s' -> %s %s (status %d)",
                    rule.name, method, url, resp.status_code,
                )
                status = "success" if resp.status_code < 400 else "failed"
                await _update_event_status(event_id, "api_call", status)
            except httpx.TimeoutException:
                await _update_event_status(event_id, "api_call", "failed", f"Timeout on {method} {url}")
            except httpx.RequestError as exc:
                await _update_event_status(event_id, "api_call", "failed", str(exc))
        return

    ok, detail = await deliver_signed(
        method, url, payload, headers=headers, secret=secret,
        params=query_params, timeout=timeout,
    )
    if ok:
        logger.info("API call fired for rule '%s' -> %s %s (%s)", rule.name, method, url, detail)
        await _update_event_status(event_id, "api_call", "success")
    else:
        await _update_event_status(event_id, "api_call", "failed", detail)


async def _execute_broadcast(action, observation_data, rule, event_id, ctx):
    from services.api.ws import broadcast

    payload_template = action.get("payload_template")
    if payload_template:
        message = render(payload_template, ctx)
        if isinstance(message, dict):
            message.setdefault("type", "event")
    else:
        message = {"type": "event", **_build_default_payload(ctx)}

    extra = action.get("extra_fields", {})
    if isinstance(message, dict) and extra:
        message.update(render(extra, ctx))

    try:
        await broadcast(message)
        await _update_event_status(event_id, "broadcast", "success")
    except Exception as exc:
        await _update_event_status(event_id, "broadcast", "failed", str(exc))


async def _execute_notify(action, observation_data, rule, event_id, ctx):
    from services.api.ws import broadcast

    template = action.get("message", "Rule '{{rule_name}}' triggered")
    # Back-compat. support {rule_name} style (single brace) plus {{rule_name}} style.
    legacy = template.replace("{rule_name}", rule.name).replace(
        "{camera_id}", observation_data.get("camera_id", "unknown")
    )
    message_text = render(legacy, ctx)
    title_text = render(action.get("title", ""), ctx) if action.get("title") else None

    try:
        async with async_session() as db:
            notif = Notification(
                message=message_text,
                severity=action.get("severity", "info"),
                rule_id=rule.id,
                camera_id=uuid.UUID(observation_data["camera_id"]) if observation_data.get("camera_id") else None,
                observation_id=(
                    uuid.UUID(observation_data["observation_id"])
                    if observation_data.get("observation_id") else None
                ),
            )
            db.add(notif)
            await db.commit()
            await db.refresh(notif)
            notif_id = str(notif.id)
    except Exception:
        logger.exception("Failed to persist notification for rule '%s'", rule.name)
        notif_id = str(uuid.uuid4())

    notification = {
        "type": "notification",
        "id": notif_id,
        "event_id": str(event_id),
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "message": message_text,
        "severity": action.get("severity", "info"),
        "camera_id": observation_data.get("camera_id"),
        "timestamp": observation_data.get("timestamp"),
    }
    if title_text:
        notification["title"] = title_text

    try:
        await broadcast(notification)
        await _update_event_status(event_id, "notify", "success")
    except Exception as exc:
        await _update_event_status(event_id, "notify", "failed", str(exc))


async def _execute_email(action, observation_data, rule, event_id, ctx):
    from shared.email import send_email

    recipient_tpl = action.get("to")
    if not recipient_tpl:
        await _update_event_status(event_id, "email", "failed", "Missing 'to' in email action")
        return
    recipient = render(recipient_tpl, ctx)

    from shared.email import resolve_smtp
    smtp_cfg = await resolve_smtp()
    if not smtp_cfg["host"]:
        await _update_event_status(event_id, "email", "failed", "SMTP not configured (Settings -> Email alerts)")
        return

    subject = render(action.get("subject", "Nurby alert. {{rule_name}}"), ctx)
    body = render(action.get("body", action.get("body_text", "Rule {{rule_name}} fired at {{timestamp}}")), ctx)

    try:
        await send_email(to=recipient, subject=subject, body=body)
        await _update_event_status(event_id, "email", "success")
    except Exception as exc:
        await _update_event_status(event_id, "email", "failed", str(exc))


# ── VLM call action ──

async def _get_provider_by_kind(kind: str) -> Provider | None:
    # Normalize "gemini" alias to "google" for the DB column kind.
    norm = "google" if kind == "gemini" else kind
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Provider).where(Provider.kind == norm, Provider.active.is_(True)).limit(1)
            )
            return result.scalar_one_or_none()
    except Exception:
        logger.exception("Failed to load VLM provider %s", kind)
        return None


def _load_thumbnail_b64(observation_data: dict) -> str | None:
    path = observation_data.get("thumbnail_path")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        logger.exception("Could not load thumbnail %s", path)
        return None


def _validate_json(obj, schema: dict | None) -> tuple[bool, str | None]:
    if not schema:
        return True, None
    try:
        import jsonschema  # type: ignore
    except ImportError:
        logger.warning("jsonschema not installed. skipping validation")
        return True, None
    try:
        jsonschema.validate(instance=obj, schema=schema)
        return True, None
    except jsonschema.ValidationError as exc:  # type: ignore
        return False, str(exc.message)


async def _vlm_openai(provider, model, system, user_prompt, image_b64, schema, timeout):
    body = {
        "model": model,
        "max_tokens": 600,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
        ],
    }
    if image_b64:
        body["messages"][1]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "low"},
        })
    if schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "rule_output", "schema": schema, "strict": True},
        }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{provider.base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {provider.api_key}"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _vlm_anthropic(provider, model, system, user_prompt, image_b64, schema, timeout):
    content = [{"type": "text", "text": user_prompt}]
    if image_b64:
        content.insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64},
        })
    body = {
        "model": model,
        "max_tokens": 800,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }
    if schema:
        body["tools"] = [{"name": "rule_output", "description": "Return the structured result", "input_schema": schema}]
        body["tool_choice"] = {"type": "tool", "name": "rule_output"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{provider.base_url}/v1/messages",
            headers={
                "x-api-key": provider.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        if schema:
            for block in data.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "rule_output":
                    return json.dumps(block.get("input", {}))
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
        return ""


async def _vlm_google(provider, model, system, user_prompt, image_b64, schema, timeout):
    parts = [{"text": user_prompt}]
    if image_b64:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image_b64}})
    gen_config = {"maxOutputTokens": 800}
    if schema:
        gen_config["responseMimeType"] = "application/json"
        gen_config["responseSchema"] = schema
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": parts}],
        "generationConfig": gen_config,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{provider.base_url}/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": provider.api_key},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def _vlm_ollama(provider, model, system, user_prompt, image_b64, schema, timeout):
    body = {
        "model": model,
        "prompt": user_prompt,
        "system": system,
        "stream": False,
    }
    if image_b64:
        body["images"] = [image_b64]
    if schema:
        body["format"] = schema
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{provider.base_url}/api/generate", json=body)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")


PROVIDER_SUPPORTS_SCHEMA = {"openai", "anthropic", "google", "gemini", "ollama"}


async def _call_vlm(provider_kind, provider, model, system, user_prompt, image_b64, schema, timeout):
    if provider_kind == "openai":
        return await _vlm_openai(provider, model, system, user_prompt, image_b64, schema, timeout)
    if provider_kind == "anthropic":
        return await _vlm_anthropic(provider, model, system, user_prompt, image_b64, schema, timeout)
    if provider_kind in ("google", "gemini"):
        return await _vlm_google(provider, model, system, user_prompt, image_b64, schema, timeout)
    if provider_kind == "ollama":
        return await _vlm_ollama(provider, model, system, user_prompt, image_b64, schema, timeout)
    raise RuntimeError(f"unsupported provider {provider_kind}")


def _extract_json(text: str) -> str:
    """Pull the first JSON object substring from a possibly messy reply."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


async def _execute_vlm_call(action, observation_data, rule, event_id, ctx):
    """Run a VLM query, optionally structured, and bind output to vars."""
    provider_kind = action.get("provider", "openai")
    model_tpl = action.get("model") or ""
    system_tpl = action.get("system") or "{{defaults.system}}"
    prompt_tpl = action.get("prompt") or "Describe the scene."
    attach_image = bool(action.get("attach_image", False))
    schema = action.get("response_schema")
    output_name = action.get("output")
    max_retries = int(action.get("max_retries", 1))
    on_error = action.get("on_error", "continue")
    fallback_value = action.get("fallback_value")
    timeout_ms = int(action.get("timeout_ms", 20000))
    timeout_s = max(1.0, timeout_ms / 1000.0)

    provider = await _get_provider_by_kind(provider_kind)
    if not provider:
        err = f"No active provider of kind {provider_kind}"
        await _update_event_status(event_id, "vlm_call", "failed", err)
        return _apply_vlm_error(observation_data, output_name, on_error, fallback_value, err)

    model = render(model_tpl, ctx) or provider.default_model or ""
    system = render(system_tpl, ctx)
    user_prompt = render(prompt_tpl, ctx)

    if schema and provider_kind not in PROVIDER_SUPPORTS_SCHEMA:
        user_prompt = (
            f"{user_prompt}\n\nReply with only JSON matching this schema. {json.dumps(schema)}"
        )

    image_b64 = _load_thumbnail_b64(observation_data) if attach_image else None

    last_error: str | None = None
    parsed = None
    raw_text = ""
    attempt_prompt = user_prompt

    for attempt in range(max_retries + 1):
        try:
            raw_text = await asyncio.wait_for(
                _call_vlm(provider_kind, provider, model, system, attempt_prompt, image_b64, schema, timeout_s),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            last_error = f"timeout after {timeout_ms}ms"
            continue
        except Exception as exc:
            last_error = f"provider error. {exc}"
            continue

        if not schema:
            parsed = raw_text
            last_error = None
            break

        try:
            parsed = json.loads(_extract_json(raw_text))
        except Exception as exc:
            last_error = f"json parse failed. {exc}"
            attempt_prompt = (
                f"{user_prompt}\n\nPrevious reply was not valid JSON. Error. {exc}. "
                f"Return only valid JSON matching the schema."
            )
            continue

        ok, err = _validate_json(parsed, schema)
        if ok:
            last_error = None
            break
        last_error = f"schema invalid. {err}"
        attempt_prompt = (
            f"{user_prompt}\n\nPrevious reply failed validation. Error. {err}. "
            f"Fix and return only valid JSON."
        )

    if last_error:
        logger.warning("vlm_call failed for rule '%s'. %s", rule.name, last_error)
        await _update_event_status(event_id, "vlm_call", "failed", last_error)
        return _apply_vlm_error(observation_data, output_name, on_error, fallback_value, last_error)

    if output_name:
        vars_bag = observation_data.setdefault("vars", {})
        vars_bag[output_name] = parsed

    await _update_event_status(event_id, "vlm_call", "success")


def _apply_vlm_error(observation_data, output_name, on_error, fallback_value, err_msg):
    if on_error == "fallback" and output_name:
        vars_bag = observation_data.setdefault("vars", {})
        vars_bag[output_name] = fallback_value
    if on_error == "stop":
        raise RuntimeError(f"vlm_call stopped chain. {err_msg}")
    # continue. no-op


# ── Verify action (VLM confirmation gate) ──


async def _record_verify_on_event(event_id: uuid.UUID, verify_result: dict) -> None:
    """Stamp the verification outcome onto Event.payload['verify'] so the
    timeline + the agent can see "fired but VLM rejected, suppressed".

    JSON columns need an explicit reassignment for SQLAlchemy to detect
    the mutation, so we copy, set, and reassign payload wholesale.
    """
    try:
        async with async_session() as db:
            event = await db.get(Event, event_id)
            if event is None:
                return
            payload = dict(event.payload or {})
            payload["verify"] = verify_result
            event.payload = payload
            await db.commit()
    except Exception:
        logger.exception("Failed to record verify result on event %s", event_id)


async def _execute_verify(action, observation_data, rule, event_id, ctx):
    """Confirm the triggering observation actually shows what the rule
    claims before the rest of the chain runs.

    Calls the agent analyzer (``analyze_frame_target``) with the verify
    question against the triggering observation's frame. The analyzer
    already owns the eternal frame cache, so a repeat verification of the
    same observation+question+model is free.

    Gate. The verification PASSES only when ``verdict == "yes"`` AND
    ``confidence >= min_confidence``. Anything else (no, uncertain,
    cannot_tell, low confidence, missing frame, or an analyzer error) is
    a FAIL. On a fail with ``on_fail == "stop"`` we raise RuntimeError so
    the engine's existing chain-abort path suppresses every later action
    (the notification, telegram, etc). On ``on_fail == "continue"`` we log
    and let the chain proceed.
    """
    question = (action.get("question") or "").strip()
    if not question:
        await _update_event_status(event_id, "verify", "failed", "Missing 'question' in verify action")
        # No question to ask. Treat as a hard fail so a misconfigured
        # rule does not silently let everything through.
        await _apply_verify_outcome(
            action, observation_data, rule, event_id,
            passed=False, verdict="cannot_tell", confidence=0.0,
            question=question, summary="verify action has no question",
        )
        return

    provider_id_raw = action.get("provider_id")
    provider_id: uuid.UUID | None = None
    if provider_id_raw:
        try:
            provider_id = uuid.UUID(str(provider_id_raw))
        except (ValueError, TypeError):
            provider_id = None

    try:
        min_confidence = float(action.get("min_confidence", 0.6))
    except (TypeError, ValueError):
        min_confidence = 0.6

    on_fail = action.get("on_fail", "stop")
    if on_fail not in ("stop", "continue"):
        on_fail = "stop"

    observation_id = observation_data.get("observation_id")

    # No observation to verify against. Without a frame we cannot
    # confirm anything, so treat it as cannot_tell -> fail.
    if not observation_id:
        logger.info("verify for rule '%s' has no observation_id. treating as cannot_tell", rule.name)
        await _apply_verify_outcome(
            action, observation_data, rule, event_id,
            passed=False, verdict="cannot_tell", confidence=0.0,
            question=question, summary="no observation frame to verify",
        )
        return

    try:
        obs_uuid = uuid.UUID(str(observation_id))
    except (ValueError, TypeError):
        await _apply_verify_outcome(
            action, observation_data, rule, event_id,
            passed=False, verdict="cannot_tell", confidence=0.0,
            question=question, summary="invalid observation id",
        )
        return

    # Call the analyzer. It reads ctx.db (optional. None -> own session)
    # and ctx.run_id (optional. None -> skips audit persistence but still
    # returns the answer). We pass a tiny attribute-bag ctx with both
    # unset so the analyzer runs read-only against its own session.
    analyzer_ctx = _VerifyCtx()
    try:
        from services.agent.analyzer import analyze_frame_target

        result = await analyze_frame_target(
            analyzer_ctx,
            obs_uuid,
            question,
            provider_id=provider_id,
        )
    except Exception:
        logger.exception("verify analyzer call failed for rule '%s'", rule.name)
        await _apply_verify_outcome(
            action, observation_data, rule, event_id,
            passed=False, verdict="cannot_tell", confidence=0.0,
            question=question, summary="analyzer error",
        )
        return

    answer = result.answer or {}
    # An analyzer hard failure returns an answer dict carrying an
    # ``error`` key (e.g. media_evicted, no_provider). No frame =
    # cannot_tell -> fail.
    if answer.get("error"):
        verdict = "cannot_tell"
        confidence = 0.0
        summary = f"analyzer. {answer['error']}"
    else:
        verdict = answer.get("verdict", "cannot_tell")
        try:
            confidence = float(answer.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        summary = answer.get("summary", "")

    passed = verdict == "yes" and confidence >= min_confidence

    await _apply_verify_outcome(
        action, observation_data, rule, event_id,
        passed=passed, verdict=verdict, confidence=confidence,
        question=question, summary=summary,
    )


class _VerifyCtx:
    """Minimal ctx object for the analyzer. ``db`` and ``run_id`` are
    both None so the analyzer opens its own read-only session and skips
    agent-run audit persistence while still returning the verdict."""

    db = None
    run_id = None
    tool_call_id = None


async def _apply_verify_outcome(
    action, observation_data, rule, event_id,
    *, passed, verdict, confidence, question, summary,
):
    """Record the verify result onto the event and decide whether to
    abort the chain. Shared by every exit path of ``_execute_verify`` so
    the audit stamp is never skipped."""
    verify_result = {
        "passed": bool(passed),
        "verdict": verdict,
        "confidence": confidence,
        "question": question,
        "summary": summary,
    }
    await _record_verify_on_event(event_id, verify_result)

    if passed:
        logger.info(
            "verify PASSED for rule '%s'. verdict=%s conf=%.2f", rule.name, verdict, confidence,
        )
        await _update_event_status(event_id, "verify", "success")
        return

    on_fail = action.get("on_fail", "stop")
    if on_fail not in ("stop", "continue", "demote"):
        on_fail = "stop"

    if on_fail == "demote":
        # Keep the event as a record but downgrade it out of the alert
        # tier, and stop the chain so notifications never fire for it.
        # Strictly better than stop-or-nothing: the footage trail and the
        # review-page entry survive, the 2am siren does not.
        try:
            async with async_session() as db:
                ev = await db.get(Event, event_id)
                if ev is not None:
                    ev.severity = "detection"
                    await db.commit()
        except Exception:
            logger.exception("verify demote failed to update event %s", event_id)
        await _update_event_status(
            event_id, "verify", "skipped",
            f"verify failed. demoted to detection ({verdict} conf={confidence:.2f})",
        )
        raise RuntimeError(f"verify failed: demoted to detection ({verdict})")

    if on_fail == "stop":
        logger.info(
            "verify FAILED for rule '%s'. verdict=%s conf=%.2f. stopping chain",
            rule.name, verdict, confidence,
        )
        await _update_event_status(
            event_id, "verify", "skipped", f"verify failed. {verdict} conf={confidence:.2f}",
        )
        raise RuntimeError(f"verify failed: {verdict} conf={confidence}")

    logger.info(
        "verify FAILED for rule '%s'. verdict=%s conf=%.2f. continuing (on_fail=continue)",
        rule.name, verdict, confidence,
    )
    await _update_event_status(
        event_id, "verify", "success", f"verify failed but on_fail=continue. {verdict}",
    )


# ── Locate action (FindAnything visual-grounding condition) ──
#
# A deterministic, user-authored, post-trigger condition (design §3.7): a
# cheap trigger (motion / a coarse YOLO label) fires first, THEN this runs the
# grounding model on the triggering frame and the action chain branches on the
# result via {{vars.<output>.found}}. It is NOT a live trigger predicate (the
# engine cannot afford a GPU call inside evaluate()) and an LLM never decides
# when it fires.
#
# Correctness gate (design §6): a raw grounding box hallucinates, so by default
# a located box must be CORROBORATED by a cheap signal in the same region (a
# YOLO detection overlapping it) before `found` is true. This is why search
# ships before autonomous rules, and why the rule path keeps a human-authored
# deterministic gate around the model.


async def _record_locate_on_event(event_id: uuid.UUID, locate_result: dict) -> None:
    """Stamp the locate outcome onto Event.payload['locate'] for the timeline
    and audit trail (mirrors _record_verify_on_event)."""
    try:
        async with async_session() as db:
            event = await db.get(Event, event_id)
            if event is None:
                return
            payload = dict(event.payload or {})
            payload["locate"] = locate_result
            event.payload = payload
            await db.commit()
    except Exception:
        logger.exception("Failed to record locate result on event %s", event_id)


def _iou(a: tuple, b: tuple) -> float:
    """IoU of two normalized [x1,y1,x2,y2] boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _corroborates(boxes, observation_data: dict, min_overlap: float) -> bool:
    """True when at least one located box overlaps a cheap detection signal.

    Uses the YOLO object detections already on the frame as the corroborating
    signal: a real "chicken" box should overlap something the detector also
    saw moving/standing there. Detection bboxes are pixels, so we normalize
    them with the frame dims before comparing to the normalized grounding box.
    Without usable frame dims or any detections we cannot corroborate, so we
    return False (fail safe. the gate suppresses rather than over-fires).
    """
    fw = observation_data.get("frame_width") or 0
    fh = observation_data.get("frame_height") or 0
    if fw <= 0 or fh <= 0:
        return False
    objs = (observation_data.get("object_detections") or {}).get("objects") or []
    det_norm: list[tuple] = []
    for d in objs:
        bb = d.get("bbox")
        if isinstance(bb, (list, tuple)) and len(bb) == 4:
            det_norm.append((bb[0] / fw, bb[1] / fh, bb[2] / fw, bb[3] / fh))
    if not det_norm:
        return False
    for gb in boxes:
        for db in det_norm:
            if _iou(gb.bbox_norm, db) >= min_overlap:
                return True
    return False


def _load_locate_frame(observation_data: dict):
    """Load the triggering frame as a BGR ndarray for grounding.

    Prefers the thumbnail path already on the live rule_data, falling back to
    the stored Observation row. Returns None when no frame is available (the
    caller then treats the locate as a fail, never a silent pass)."""
    import cv2

    from shared.config import settings as _settings
    from shared.paths import resolve_inside

    path = observation_data.get("thumbnail_path")
    if path:
        safe = resolve_inside(path, _settings.thumbnails_path)
        if safe:
            img = cv2.imread(safe)
            if img is not None:
                return img
    return None


async def _ground_locate(frame, prompt: str):
    """Run grounding on the background (rule) priority lane."""
    from services.grounding.client import get_client

    return await get_client().ground(frame, prompt, interactive=False)


async def _ground_locate_cached(observation_data: dict, prompt: str):
    """Ground ``prompt`` on the observation's frame, reusing the persistent
    grounding cache keyed by (observation_id, prompt, model_revision). Returns
    ``(boxes, error)`` — ``boxes`` is a list of GroundedBox, ``error`` a string.

    On a cache hit there is no GPU call and no frame load, so a repeat locate of
    the same frame+prompt — or several concurrent sequence instances waiting on
    the same locate step — pay for one inference, not N. Only the raw boxes are
    cached; corroboration/`found` stay rule-specific and are recomputed by the
    caller. The cache is best-effort: any read/write failure degrades to a live
    grounding call, never an error."""
    from services.grounding.cache import get_cached_grounding, store_grounding
    from services.grounding.parse import GroundedBox
    from shared.config import settings as _settings

    obs_id = observation_data.get("observation_id")
    revision = getattr(_settings, "grounding_model_revision", "main") or "main"

    if obs_id:
        cached = await get_cached_grounding(obs_id, prompt, revision)
        if cached is not None:
            # Only bbox_norm is read downstream (corroboration + vars); bbox_px
            # and label aren't cached, so fill placeholders.
            boxes = [
                GroundedBox(bbox_norm=tuple(b), bbox_px=(0, 0, 0, 0), label="")
                for b in (cached.get("boxes") or [])
                if isinstance(b, (list, tuple)) and len(b) == 4
            ]
            return boxes, None

    frame = await asyncio.to_thread(_load_locate_frame, observation_data)
    if frame is None:
        return None, "no frame to inspect"
    result = await _ground_locate(frame, prompt)
    if result.error:
        return None, result.error
    boxes = result.boxes
    if obs_id:
        await store_grounding(
            obs_id, prompt, revision,
            found=bool(boxes), corroborated=False,
            boxes=[list(b.bbox_norm) for b in boxes],
        )
    return boxes, None


async def run_locate_check(check: dict, observation_data: dict) -> bool:
    """Run a FindAnything locate as a plain boolean check, with no action-chain
    side effects (no vars binding, no event stamping, no on_fail).

    Used by temporal sequence step checks: the sequence engine only calls this
    while an instance is actively waiting on this step (and after any cheap
    pre_gate passes), so GPU cost stays bounded to in-flight sequences. Returns
    False on any failure (no prompt, no frame, grounding error) so a step never
    silently passes. See docs/sequence-rules-design.md."""
    prompt = (check.get("prompt") or "").strip()
    if not prompt:
        return False
    require_corroboration = bool(check.get("require_corroboration", False))
    try:
        min_overlap = float(check.get("min_overlap", 0.1))
    except (TypeError, ValueError):
        min_overlap = 0.1

    boxes, err = await _ground_locate_cached(observation_data, prompt)
    if err is not None:
        logger.info("sequence locate check could not run. %s", err)
        return False
    if not boxes:
        return False
    if require_corroboration:
        return _corroborates(boxes, observation_data, min_overlap)
    return True


async def run_verify_check(check: dict, observation_data: dict) -> bool:
    """Run a verify (VLM yes/no) as a plain boolean check, no chain side effects.
    Passes only when verdict==yes AND confidence>=min_confidence. Used by
    sequence verify-step checks. Returns False on any failure."""
    question = (check.get("question") or "").strip()
    observation_id = observation_data.get("observation_id")
    if not question or not observation_id:
        return False
    try:
        obs_uuid = uuid.UUID(str(observation_id))
    except (ValueError, TypeError):
        return False
    try:
        min_confidence = float(check.get("min_confidence", 0.6))
    except (TypeError, ValueError):
        min_confidence = 0.6
    provider_id = None
    if check.get("provider_id"):
        try:
            provider_id = uuid.UUID(str(check["provider_id"]))
        except (ValueError, TypeError):
            provider_id = None
    try:
        from services.agent.analyzer import analyze_frame_target

        result = await analyze_frame_target(_VerifyCtx(), obs_uuid, question, provider_id=provider_id)
    except Exception:
        logger.info("sequence verify check could not run", exc_info=True)
        return False
    answer = result.answer or {}
    if answer.get("error"):
        return False
    verdict = answer.get("verdict", "cannot_tell")
    try:
        confidence = float(answer.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return verdict == "yes" and confidence >= min_confidence


async def run_grounding_check(check: dict, observation_data: dict) -> bool:
    """Dispatch a grounding-backed sequence step check: verify (VLM yes/no) or
    locate (FindAnything box)."""
    if (check or {}).get("type") == "verify":
        return await run_verify_check(check, observation_data)
    return await run_locate_check(check, observation_data)


async def _execute_locate(action, observation_data, rule, event_id, ctx):
    """Locate ``prompt`` in the triggering frame and branch the chain on it."""
    prompt = render(action.get("prompt") or "", ctx).strip()
    output_name = action.get("output")
    on_fail = action.get("on_fail", "stop")
    if on_fail not in ("stop", "continue"):
        on_fail = "stop"
    require_corroboration = bool(action.get("require_corroboration", False))
    try:
        min_overlap = float(action.get("min_overlap", 0.1))
    except (TypeError, ValueError):
        min_overlap = 0.1

    if not prompt:
        await _update_event_status(event_id, "locate", "failed", "missing 'prompt'")
        await _apply_locate_outcome(
            action, observation_data, rule, event_id, output_name,
            found=False, boxes=[], corroborated=False, prompt="",
            summary="locate action has no prompt",
        )
        return

    boxes, err = await _ground_locate_cached(observation_data, prompt)
    if err is not None:
        logger.info("locate for rule '%s' could not run. %s", rule.name, err)
        await _apply_locate_outcome(
            action, observation_data, rule, event_id, output_name,
            found=False, boxes=[], corroborated=False, prompt=prompt,
            summary=err,
        )
        return

    # Corroboration is a *signal*, not a veto by default. FindAnything exists
    # for open-vocabulary objects YOLO can't detect (a chicken), so requiring
    # overlap with a YOLO box would silently fail exactly those. Always compute
    # it (surfaced as vars.<output>.corroborated) but only let it veto `found`
    # when the user explicitly opts in via require_corroboration.
    corroborated = _corroborates(boxes, observation_data, min_overlap) if boxes else False
    found = bool(boxes) and (corroborated or not require_corroboration)

    await _apply_locate_outcome(
        action, observation_data, rule, event_id, output_name,
        found=found, boxes=boxes, corroborated=corroborated, prompt=prompt,
        summary=f"{len(boxes)} box(es), corroborated={corroborated}",
    )


async def _apply_locate_outcome(
    action, observation_data, rule, event_id, output_name,
    *, found, boxes, corroborated, prompt, summary,
):
    """Bind {{vars.<output>.*}}, record the outcome, and apply on_fail. Shared
    by every exit of _execute_locate so the audit stamp is never skipped."""
    if output_name:
        vars_bag = observation_data.setdefault("vars", {})
        vars_bag[output_name] = {
            "found": bool(found),
            "count": len(boxes) if found else 0,
            "label": prompt,
            "corroborated": bool(corroborated),
            "boxes": [list(b.bbox_norm) for b in boxes],
        }

    await _record_locate_on_event(event_id, {
        "found": bool(found),
        "count": len(boxes),
        "corroborated": bool(corroborated),
        "prompt": prompt,
        "summary": summary,
    })

    on_fail = action.get("on_fail", "stop")
    if on_fail not in ("stop", "continue"):
        on_fail = "stop"

    if found:
        logger.info("locate FOUND for rule '%s'. %s", rule.name, summary)
        await _update_event_status(event_id, "locate", "success")
        return

    if on_fail == "stop":
        logger.info("locate NOT FOUND for rule '%s'. stopping chain. %s", rule.name, summary)
        await _update_event_status(event_id, "locate", "skipped", f"locate not found. {summary}")
        raise RuntimeError(f"locate stopped chain. {summary}")

    logger.info("locate NOT FOUND for rule '%s'. continuing (on_fail=continue)", rule.name)
    await _update_event_status(
        event_id, "locate", "success", f"locate not found but on_fail=continue. {summary}",
    )


# ── Telegram action ──

# Variables documented for the rule builder UI. Kept in sync with the
# frontend rule-builder chip list.
TELEGRAM_TEMPLATE_VARS = (
    "rule_name",
    "camera_name",
    "timestamp_local",
    "vlm_description",
    "detections_summary",
    "observation_id",
    "event_id",
    "event_url",
)


# Phase 2 inline button action enum. Extending this tuple in later
# phases (e.g. ``name_cluster`` for Phase 4 face cluster naming) is
# the documented extension point. The verify path in
# ``telegram_poller._handle_callback_query`` and the schema validator
# in ``shared.schemas._VALID_TELEGRAM_BUTTON_ACTIONS`` must be kept in
# lockstep.
TELEGRAM_BUTTON_ACTIONS = (
    "ack",
    "mute_event",
    "snooze_rule",
    "open",
    # Phase 4. These are NOT exposed in the rule builder UI. They are
    # emitted only by the system-initiated cluster naming prompts and
    # the optional ask-yes-no dialog. Listed here so the callback
    # dispatch path in telegram_poller passes its allowlist check.
    "open_cluster",
    "name_cluster_telegram",
    "yn_yes",
    "yn_no",
)


def _resolve_event_url(event_id) -> str | None:
    """Build a web UI deep link for an event. Returns None when the
    operator has not configured ``public_base_url``; callers must
    decide whether to render a button or surface a warning."""
    from shared.config import settings
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        return None
    return f"{base}/rules?event={event_id}"


def _expand_telegram_template(template: str, ctx: dict) -> str:
    """Render a template using both `{var}` and `{{var}}` styles.

    Mirrors the back-compat behaviour in the notify action so users
    who learned the single-brace shorthand in Notification templates
    don't have to learn a new dialect for Telegram."""
    legacy = template
    for key in TELEGRAM_TEMPLATE_VARS:
        legacy = legacy.replace("{" + key + "}", _stringify_ctx(ctx.get(key)))
    rendered = render(legacy, ctx, strict=False)
    return rendered if isinstance(rendered, str) else str(rendered)


def _stringify_ctx(val) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, default=str)
        except Exception:
            return str(val)
    return str(val)


def _build_inline_keyboard(buttons, event_id, rule_id, ctx) -> dict | None:
    """Render the action's button spec to a Telegram
    InlineKeyboardMarkup with HMAC-signed callback_data.

    One row per button (Telegram allows multi-column, but stacking
    works on every client width and matches the 4-button vertical
    layout used in the rule builder mock).

    Buttons of action ``open`` use ``url=`` (no callback signing).
    Other actions get a base64 JSON payload with short keys ``a, e,
    r, d`` to stay under Telegram's 64-byte ``callback_data`` cap.
    """
    if not buttons:
        return None
    from services.events.templates import render as _render
    from services.notify.telegram import CALLBACK_DATA_MAX, sign_callback
    rows = []
    for spec in buttons:
        if not isinstance(spec, dict):
            continue
        action = str(spec.get("action") or "")
        label = str(spec.get("label") or action or "Button")
        if action == "open":
            url_tpl = spec.get("url") or "{event_url}"
            try:
                url = _render(url_tpl, ctx, strict=False)
            except Exception:
                url = ""
            url = url.strip() if isinstance(url, str) else ""
            # Skip the open button when {event_url} resolves empty
            # (operator has not set public_base_url). Better to drop
            # the button than ship a 400-on-tap broken URL.
            if not url or not (url.startswith("http://") or url.startswith("https://")):
                logger.debug(
                    "telegram open button skipped. unresolved url for rule=%s", rule_id,
                )
                continue
            rows.append([{"text": label, "url": url}])
            continue

        if action not in TELEGRAM_BUTTON_ACTIONS:
            continue
        payload: dict = {"a": action, "e": str(event_id), "r": str(rule_id)}
        duration = spec.get("duration_seconds")
        if duration is not None:
            try:
                payload["d"] = int(duration)
            except (TypeError, ValueError):
                pass
        signed = sign_callback(json.dumps(payload, separators=(",", ":")))
        # Telegram rejects callback_data > 64 bytes. Drop the button
        # rather than silently breaking it; this only happens if a
        # rule ships extra payload keys we did not plan for.
        if len(signed.encode("utf-8")) > CALLBACK_DATA_MAX:
            logger.warning(
                "telegram button '%s' callback_data exceeds 64 bytes. dropping",
                label,
            )
            continue
        rows.append([{"text": label, "callback_data": signed}])
    if not rows:
        return None
    return {"inline_keyboard": rows}


async def _telegram_suppression_reason(rule, event_id, observation_data) -> str | None:
    """Check rule-level snooze and per-event mute. Returns a short
    reason string when the message should be suppressed, or None when
    it should be delivered. Snooze wins over mute because snooze is
    rule-wide (see comment on Rule.snoozed_until)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    snoozed_until = getattr(rule, "snoozed_until", None)
    if snoozed_until is not None and snoozed_until > now:
        when = snoozed_until.astimezone().strftime("%H:%M")
        return f"rule_snoozed_until_{when}"

    camera_id_raw = observation_data.get("camera_id")
    if not camera_id_raw:
        return None
    try:
        camera_uuid = uuid.UUID(str(camera_id_raw))
    except (ValueError, TypeError):
        return None

    from datetime import timedelta

    from sqlalchemy import select as _select

    from shared.models import Event as _Event
    from shared.models import Observation as _Observation
    cooldown = max(0, int(getattr(rule, "cooldown_seconds", 60) or 60))
    window_start = now - timedelta(seconds=cooldown)
    try:
        async with async_session() as db:
            stmt = (
                _select(_Event)
                .join(_Observation, _Event.observation_id == _Observation.id)
                .where(_Event.rule_id == rule.id)
                .where(_Observation.camera_id == camera_uuid)
                .where(_Event.fired_at >= window_start)
                .where(_Event.acked_at.is_(None))
                .where(_Event.muted_until.is_not(None))
                .where(_Event.muted_until > now)
            )
            result = await db.execute(stmt)
            muted_event = result.scalars().first()
            if muted_event is not None:
                when = muted_event.muted_until.astimezone().strftime("%H:%M")
                return f"event_muted_until_{when}"
    except Exception:
        logger.exception("telegram suppression lookup failed for rule=%s", rule.id)
    return None


async def _execute_telegram(action, observation_data, rule, event_id, ctx):
    """Resolve a paired Telegram channel and send the rendered message.

    Phase 2. include_thumbnail wires :meth:`TelegramAPI.send_photo`
    with the on-disk observation snapshot. Buttons render an inline
    keyboard with HMAC-signed callback_data. Rule snooze and per-event
    mute suppress the send before the network call.
    """
    from services.notify.telegram import (
        PHOTO_CAPTION_MAX,
        PHOTO_FALLBACK_SENTINEL,
        TelegramAPI,
        TelegramError,
        store_message_index,
    )
    from shared.crypto import InvalidToken, decrypt_secret
    from shared.models import TelegramChannel

    channel_id_raw = action.get("channel_id")
    if not channel_id_raw:
        await _update_event_status(event_id, "telegram", "failed", "Missing channel_id")
        return

    try:
        channel_uuid = uuid.UUID(str(channel_id_raw))
    except (ValueError, TypeError):
        await _update_event_status(event_id, "telegram", "failed", "Invalid channel_id")
        return

    # Suppression. Check before loading the channel so we don't waste
    # a DB round trip when the rule is snoozed.
    suppress_reason = await _telegram_suppression_reason(rule, event_id, observation_data)
    if suppress_reason:
        logger.info(
            "telegram send suppressed for rule='%s' reason=%s", rule.name, suppress_reason,
        )
        await _update_event_status(event_id, "telegram", "skipped", suppress_reason)
        return

    template = action.get("template") or "Rule {rule_name} fired on {camera_name}"
    silent = bool(action.get("silent"))
    include_thumbnail = bool(action.get("include_thumbnail"))
    buttons_spec = action.get("buttons") or []

    async with async_session() as db:
        ch = await db.get(TelegramChannel, channel_uuid)
        if ch is None:
            await _update_event_status(event_id, "telegram", "failed", "Channel not found")
            return
        if not ch.enabled:
            await _update_event_status(event_id, "telegram", "failed", "Channel is disabled")
            return
        if ch.paired_at is None or not ch.chat_id:
            await _update_event_status(event_id, "telegram", "failed", "Channel is not paired")
            return
        try:
            token = decrypt_secret(ch.bot_token_enc)
        except InvalidToken:
            await _update_event_status(
                event_id, "telegram", "failed",
                "Bot token unreadable (jwt_secret rotated?). Replace it on the channel.",
            )
            return
        chat_id = ch.chat_id
        default_silent = bool(ch.default_silent)
        channel_label = ch.label

    text = _expand_telegram_template(template, ctx)
    if not text.strip():
        await _update_event_status(event_id, "telegram", "failed", "Rendered template is empty")
        return

    reply_markup = _build_inline_keyboard(buttons_spec, event_id, rule.id, ctx)

    # Pick send_photo vs send_message based on the thumbnail flag and
    # on-disk reality. Missing path -> fall back to text + note.
    thumbnail_path = observation_data.get("thumbnail_path") or ""
    have_thumb = bool(thumbnail_path) and os.path.exists(thumbnail_path)
    photo_mode = include_thumbnail and have_thumb

    if include_thumbnail and not have_thumb:
        # Don't fail the alert; deliver the text and annotate the
        # event so the operator can see why the photo did not arrive.
        logger.warning(
            "telegram include_thumbnail set but path missing for rule='%s' path=%r",
            rule.name, thumbnail_path,
        )

    try:
        if photo_mode:
            # Caption gets the leading part of the body, full body
            # goes as a follow-up message when it exceeds the cap.
            short_caption = text if len(text) <= PHOTO_CAPTION_MAX else text[: PHOTO_CAPTION_MAX - 1] + "…"
            photo_result = await TelegramAPI.send_photo(
                token,
                chat_id,
                thumbnail_path,
                caption=short_caption,
                parse_mode="HTML",
                disable_notification=silent or default_silent,
                reply_markup=reply_markup,
            )
            note = None
            if photo_result.get("fallback") == PHOTO_FALLBACK_SENTINEL:
                note = photo_result.get("fallback_reason") or "photo_fallback"
                logger.warning(
                    "telegram photo fallback rule='%s' reason=%s",
                    rule.name, note,
                )
            if len(text) > PHOTO_CAPTION_MAX and not photo_result.get("fallback"):
                # Photo carried the truncated caption. Follow up with
                # the full body so the user never loses content.
                try:
                    await TelegramAPI.send_message(
                        token, chat_id, text,
                        parse_mode="HTML",
                        disable_notification=silent or default_silent,
                    )
                except TelegramError:
                    logger.exception("telegram follow-up send_message failed for rule='%s'", rule.name)
            logger.info(
                "Telegram photo sent for rule='%s' channel='%s' message_id=%s",
                rule.name, channel_label, photo_result.get("message_id"),
            )
            # Phase 4. Index the outbound message so a later user
            # reply resolves back to this Event for note-taking.
            sent_msg_id = photo_result.get("message_id")
            if sent_msg_id:
                await store_message_index(
                    channel_uuid, int(sent_msg_id),
                    {
                        "event_id": str(event_id),
                        "rule_id": str(rule.id),
                        "kind": "alert",
                    },
                )
            await _update_event_status(
                event_id, "telegram",
                "success" if not note else "success",
                note,
            )
        else:
            result = await TelegramAPI.send_message(
                token,
                chat_id,
                text,
                parse_mode="HTML",
                disable_notification=silent or default_silent,
                reply_markup=reply_markup,
            )
            logger.info(
                "Telegram sent for rule '%s' channel='%s' message_id=%s",
                rule.name, channel_label, result.get("message_id"),
            )
            sent_msg_id = result.get("message_id")
            if sent_msg_id:
                await store_message_index(
                    channel_uuid, int(sent_msg_id),
                    {
                        "event_id": str(event_id),
                        "rule_id": str(rule.id),
                        "kind": "alert",
                    },
                )
            note = "thumbnail_missing" if (include_thumbnail and not have_thumb) else None
            await _update_event_status(event_id, "telegram", "success", note)
    except TelegramError as exc:
        await _update_event_status(event_id, "telegram", "failed", exc.description[:500])
        if exc.is_forbidden:
            # Bot blocked or chat gone. Disable channel + persist error
            # so the settings UI flips to "Blocked" and stops alerts
            # until the user re-enables.
            try:
                async with async_session() as db:
                    refreshed = await db.get(TelegramChannel, channel_uuid)
                    if refreshed is not None:
                        refreshed.enabled = False
                        refreshed.last_test_ok = False
                        refreshed.last_error = exc.description[:500]
                        await db.commit()
            except Exception:
                logger.exception("Failed to mark telegram channel %s blocked", channel_uuid)
