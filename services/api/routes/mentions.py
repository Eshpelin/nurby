"""Mentionable entities for the @-autocomplete.

One flat list across every entity kind a user can @-mention in a
natural-language input (Ask Nurby, dashboard composer, Describe-your-
alert). The frontend caches this per session and filters client-side.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.devices import get_preset
from shared.auth import get_current_user
from shared.database import get_db
from shared.models import Camera, Device, Person, TelegramChannel, User
from shared.schemas import MentionRef

router = APIRouter()


@router.get("")
async def list_mentionables(
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    out: list[dict] = []
    for cam_id, name in (await db.execute(select(Camera.id, Camera.name))).all():
        out.append({"kind": "camera", "id": str(cam_id), "name": name, "hint": None})
    for pid, name, nickname in (
        await db.execute(select(Person.id, Person.display_name, Person.nickname))
    ).all():
        out.append({"kind": "person", "id": str(pid), "name": name, "hint": nickname})
    for cid, label in (
        await db.execute(
            select(TelegramChannel.id, TelegramChannel.label).where(
                TelegramChannel.enabled.is_(True)
            )
        )
    ).all():
        out.append(
            {"kind": "telegram_channel", "id": str(cid), "name": label or "Telegram", "hint": None}
        )
    for did, name, preset_id in (
        await db.execute(
            select(Device.id, Device.name, Device.preset_id).where(Device.enabled.is_(True))
        )
    ).all():
        preset = get_preset(preset_id) if preset_id else None
        out.append(
            {"kind": "device", "id": str(did), "name": name,
             "hint": preset["name"] if preset else None}
        )
    out.sort(key=lambda m: (m["kind"], m["name"].lower()))
    return out


_MODEL_BY_KIND = {
    "camera": Camera,
    "person": Person,
    "telegram_channel": TelegramChannel,
    "device": Device,
}


async def verify_mentions(db: AsyncSession, mentions: list[MentionRef]) -> list[dict]:
    """Drop mention rows whose kind+id match no existing row, so a stale
    client cache can never inject ghost UUIDs into a prompt. Returns
    plain dicts ready for prompt building / persistence."""
    if not mentions:
        return []
    by_kind: dict[str, list[MentionRef]] = {}
    for m in mentions:
        by_kind.setdefault(m.kind, []).append(m)
    verified: list[dict] = []
    for kind, refs in by_kind.items():
        model = _MODEL_BY_KIND[kind]
        ids: set[uuid.UUID] = {m.id for m in refs}
        rows = await db.execute(select(model.id).where(model.id.in_(ids)))
        existing = {r[0] for r in rows.all()}
        for m in refs:
            if m.id in existing:
                verified.append({"kind": m.kind, "id": str(m.id), "name": m.name})
    return verified
