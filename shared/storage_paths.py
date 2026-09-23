"""Runtime media-storage location (issue #251, docs/operations/storage-location.md).

The deploy-level knob is ``RECORDINGS_PATH`` (and the compose-level
``NURBY_RECORDINGS_VOLUME``): where the container's recordings volume
lives. This module adds the runtime knob on top: a ``storage_recordings_dir``
app setting, chosen in the setup wizard or Settings, that redirects the
recordings root — including on bare-metal Windows installs where "which
drive" is the first question a new user asks.

Mechanism: nearly every consumer reads ``settings.recordings_path`` at
call time, so applying the override is a single assignment on the shared
``Settings`` singleton. Each process applies it at startup and then on a
throttle; the settings PATCH route applies it immediately. Consumers that
froze the path at import time (per-annotator cache dirs) were converted
to read it lazily.

Semantics worth keeping honest:
- NEW recordings land in the new root; existing files stay where they
  were written (serving resolves paths against the current root, so old
  recordings stop playing until the files are moved or the setting is
  reverted). The UI warns about exactly this.
- Reverting to None restores the env-provided default, which is captured
  once at import so re-applying can never drift.
"""

import logging
import os
import time

from shared.app_settings import get_setting
from shared.config import settings

logger = logging.getLogger(__name__)

# Env default captured at import: reverting the override must restore the
# original value even though `settings.recordings_path` itself was mutated.
ENV_DEFAULT = settings.recordings_path

_THROTTLE_SECONDS = 30.0

_applied: str | None = None
_last_check = 0.0


def env_recordings_default() -> str:
    """The env-provided recordings root (what None resolves to)."""
    return ENV_DEFAULT


def current_recordings_root() -> str:
    """What the recordings root is right now (post-override). Pure read
    of the singleton for callers that are already async-adjacent."""
    return settings.recordings_path


def in_docker() -> bool:
    """Best-effort container detection, used to shape UI guidance."""
    return os.path.exists("/.dockerenv")


def invalidate() -> None:
    """Force the next apply to re-read the setting (settings PATCH)."""
    global _last_check, _profile_roots_at
    _last_check = 0.0
    _profile_roots.clear()
    _profile_roots_at = 0.0


async def apply_storage_overrides(*, force: bool = False) -> None:
    """Reflect ``storage_recordings_dir`` onto the process-wide settings.

    Throttled so loops can call it freely; ``force`` skips the throttle
    (settings PATCH). Never raises — a failed settings read must not take
    down a sync loop.
    """
    global _applied, _last_check
    now = time.monotonic()
    if not force and now - _last_check < _THROTTLE_SECONDS:
        return
    _last_check = now
    try:
        raw = await get_setting("storage_recordings_dir", None)
    except Exception:
        logger.debug("storage override read failed", exc_info=True)
        return
    root = str(raw).strip() if raw else None
    desired = root or ENV_DEFAULT
    # Idempotence: skip only when both the stored override and the live
    # singleton already agree — so a drifted process self-heals on the
    # next apply instead of staying stuck on a stale root.
    if root == _applied and settings.recordings_path == desired:
        return
    previous = settings.recordings_path
    settings.recordings_path = desired
    _applied = root
    if desired != previous:
        logger.info(
            "Recordings root moved to %s (source: %s)",
            desired,
            "app setting" if root else "env default",
        )


# ── Per-camera roots (storage profiles) ──────────────────────────────
#
# A camera with a storage profile records under that profile's root
# instead of the global one. Roots are cached per process and refreshed
# on the same throttle as the global override; camera/profile PATCHes
# invalidate via the storage restart signal.

_profile_roots: dict[str, str] = {}
_profile_roots_at = 0.0


async def _load_profile_roots() -> dict[str, str]:
    """camera_id (str) -> enabled local profile root. Cached ~30s."""
    global _profile_roots, _profile_roots_at
    now = time.monotonic()
    if _profile_roots_at > 0 and now - _profile_roots_at < _THROTTLE_SECONDS:
        return _profile_roots
    _profile_roots_at = now
    try:
        from sqlalchemy import select

        from shared.database import async_session
        from shared.models import Camera, StorageProfile

        async with async_session() as db:
            rows = await db.execute(
                select(Camera.id, StorageProfile.root)
                .join(StorageProfile, Camera.storage_profile_id == StorageProfile.id)
                .where(StorageProfile.enabled.is_(True))
                .where(StorageProfile.kind == "local")
            )
            # Only kind="local" profiles resolve as LOCAL roots; FTP-profile
            # cameras keep the global root as their buffer (shared/
            # remote_storage.py handles their remote destination).
            _profile_roots = {str(cam_id): root for cam_id, root in rows.all()}
    except Exception:
        logger.debug("profile root load failed", exc_info=True)
    return _profile_roots


async def recordings_root_for(camera_id) -> str:
    """The recordings root a given camera writes to / is served from:
    its storage profile's root when it has one, else the global root.
    ``camera_id=None`` (or an unknown camera) resolves to the global root.
    Callers must already be async; the cache keeps this off the hot path.

    Note this only RESOLVES — reflecting the global override onto the
    singleton is the lifecycle ticks' job (API startup, manager sync,
    settings PATCH), so a stale override is never re-applied from here.
    """
    if camera_id is None:
        return settings.recordings_path
    roots = await _load_profile_roots()
    return roots.get(str(camera_id)) or settings.recordings_path
