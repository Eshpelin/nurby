"""Age-based archive tier for recordings (issue #270).

"Keep recent footage on this machine, move older footage to the cloud."
A camera's recording retention is how long footage stays LOCAL. When an
archive destination is set, recordings that age out of that window are
uploaded to it (through the same buffer-then-upload worker as FTP/S3
cameras) and removed locally, instead of being deleted. The archive has
its own lifetime (``archive_retention_days``, 0 = keep forever).

The destination is a remote storage profile (``kind`` ftp or s3). For S3
the profile's storage class decides the price/latency trade-off; Glacier
Instant Retrieval keeps playback instant, Glacier / Deep Archive need a
restore that playback requests on demand.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from shared.app_settings import get_setting

SETTING_PROFILE = "archive_profile_id"
SETTING_RETENTION = "archive_retention_days"


@dataclass(frozen=True)
class ArchiveTarget:
    profile_id: uuid.UUID
    root: str
    name: str
    kind: str
    retention_days: int  # 0 = keep forever


async def _configured_id() -> uuid.UUID | None:
    raw = await get_setting(SETTING_PROFILE, None)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def archive_target() -> ArchiveTarget | None:
    """The configured archive destination, or None when archiving is off
    or its profile is missing, disabled, or not a remote kind."""
    profile_id = await _configured_id()
    if profile_id is None:
        return None
    from shared.database import async_session
    from shared.models import StorageProfile
    from shared.remote_storage import REMOTE_KINDS

    async with async_session() as db:
        profile = await db.get(StorageProfile, profile_id)
    if profile is None or not profile.enabled or profile.kind not in REMOTE_KINDS:
        return None
    days = int(await get_setting(SETTING_RETENTION, 0) or 0)
    return ArchiveTarget(profile.id, profile.root, profile.name, profile.kind, max(0, days))


async def archive_misconfigured() -> bool:
    """Archiving was turned on but its destination no longer works, so
    recordings are being deleted instead of archived."""
    return await _configured_id() is not None and await archive_target() is None
