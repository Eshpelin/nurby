import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.vlm_queue import get_vlm_stats
from shared import heartbeat
from shared.auth import get_current_user, require_admin
from shared.config import settings
from shared.database import get_db
from shared.email import send_email
from shared.models import Camera, Observation, Recording, User
from shared.schemas import (
    CameraStorageStats,
    StorageResponse,
    SystemSettingsResponse,
    SystemSettingsUpdate,
    SystemStatus,
)

router = APIRouter()


@router.get("/status", response_model=SystemStatus)
async def get_system_status(_current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from services.api.main import START_TIME

    total = await db.scalar(select(func.count()).select_from(Camera))
    online = await db.scalar(
        select(func.count()).select_from(Camera).where(Camera.status != "offline")
    )
    recording = await db.scalar(
        select(func.count()).select_from(Camera).where(Camera.status == "recording")
    )

    return SystemStatus(
        version="0.1.0",
        cameras_total=total or 0,
        cameras_online=online or 0,
        cameras_recording=recording or 0,
        uptime_seconds=time.time() - START_TIME,
    )


@router.get("/storage", response_model=StorageResponse)
async def get_storage_stats(_current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cameras_result = await db.execute(select(Camera))
    cameras = cameras_result.scalars().all()

    rec_stats = await db.execute(
        select(
            Recording.camera_id,
            func.count(Recording.id).label("recording_count"),
            func.coalesce(func.sum(Recording.file_size_bytes), 0).label("recording_bytes"),
        ).group_by(Recording.camera_id)
    )
    rec_by_camera = {row.camera_id: row for row in rec_stats.all()}

    obs_stats = await db.execute(
        select(
            Observation.camera_id,
            func.count(Observation.id).label("observation_count"),
        ).group_by(Observation.camera_id)
    )
    obs_by_camera = {row.camera_id: row.observation_count for row in obs_stats.all()}

    camera_stats = []
    total_bytes = 0
    total_obs = 0

    for cam in cameras:
        rec = rec_by_camera.get(cam.id)
        rec_count = rec.recording_count if rec else 0
        rec_bytes = int(rec.recording_bytes) if rec else 0
        obs_count = obs_by_camera.get(cam.id, 0)

        total_bytes += rec_bytes
        total_obs += obs_count

        camera_stats.append(
            CameraStorageStats(
                camera_id=cam.id,
                camera_name=cam.name,
                recording_count=rec_count,
                recording_bytes=rec_bytes,
                observation_count=obs_count,
                retention_mode=cam.retention_mode,
                retention_days=cam.retention_days,
                retention_gb=cam.retention_gb,
            )
        )

    return StorageResponse(
        cameras=camera_stats,
        total_recording_bytes=total_bytes,
        total_observations=total_obs,
    )


@router.get("/vlm-stats")
async def get_vlm_queue_stats(_current_user: User = Depends(get_current_user)):
    """Get VLM processing stats per camera. Latency, queue depth, errors."""
    return get_vlm_stats()


@router.get("/system/pipeline-summary")
async def get_pipeline_summary(
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fleet-wide VLM backlog rollup for the pipeline page + home widget.

    Per-camera ``eta_seconds`` (from ``CameraVLMStats``) each assume that
    camera drains alone. In the real deployment many cameras share one VLM,
    so they contend for a single worker. The honest fleet ETA is therefore
    the *serial* sum of every camera's own drain time, not the max. We keep
    per-camera ETA untouched (it answers "if only this camera existed") and
    compute the serial figure here.
    """
    stats = get_vlm_stats()  # {camera_id: to_dict()}

    # Map ids -> names so the page/table need no second round-trip.
    cam_rows = (await db.execute(select(Camera.id, Camera.name))).all()
    names = {str(cid): name for cid, name in cam_rows}

    cameras = []
    total_queued = 0
    total_high = 0
    fleet_eta_seconds = 0.0
    # Weighted mean latency: weight each camera's avg by its throughput so
    # idle cameras with a stale EMA don't skew the fleet sec/frame.
    weighted_latency_num = 0.0
    weighted_latency_den = 0
    status_counts: dict[str, int] = {}
    active_calls = 0
    total_errors = 0

    for cam_id, s in stats.items():
        backlog = s.get("backlog", {})
        depth = int(backlog.get("total", 0))
        high = int(backlog.get("high", 0))
        avg = float(s.get("avg_latency", 0.0))
        calls = int(s.get("total_calls", 0))

        total_queued += depth
        total_high += high
        # Serial drain: this camera's frames each cost its own latency.
        fleet_eta_seconds += depth * avg
        if calls > 0 and avg > 0:
            weighted_latency_num += avg * calls
            weighted_latency_den += calls
        status = s.get("status", "idle")
        status_counts[status] = status_counts.get(status, 0) + 1
        active_calls += calls
        total_errors += int(s.get("total_errors", 0))

        cameras.append(
            {
                "camera_id": cam_id,
                "camera_name": names.get(str(cam_id), cam_id),
                "backlog": depth,
                "backlog_high": high,
                "avg_latency": round(avg, 2),
                "last_latency": round(float(s.get("last_latency", 0.0)), 2),
                "eta_seconds": float(backlog.get("eta_seconds", 0.0)),
                "status": status,
                "total_dropped": int(s.get("total_dropped", 0)),
                "total_errors": int(s.get("total_errors", 0)),
                "reason": s.get("reason", ""),
            }
        )

    # Worst offenders first: deepest backlog, then slowest.
    cameras.sort(key=lambda c: (c["backlog"], c["avg_latency"]), reverse=True)

    sec_per_frame = (
        round(weighted_latency_num / weighted_latency_den, 2)
        if weighted_latency_den
        else 0.0
    )
    frames_per_min = round(60.0 / sec_per_frame, 1) if sec_per_frame > 0 else 0.0

    # Health verdict drives the home-screen widget colour. "backlogged" is
    # the case the user cares about: single VLM slowly catching up.
    if any(c["status"] in ("stalled", "failed") for c in cameras):
        health = "degraded"
    elif fleet_eta_seconds > 120 or total_queued > 30:
        health = "backlogged"
    elif total_queued > 0:
        health = "catching_up"
    else:
        health = "clear"

    return {
        "health": health,
        "total_queued": total_queued,
        "total_high_priority": total_high,
        "fleet_eta_seconds": round(fleet_eta_seconds, 1),
        "sec_per_frame": sec_per_frame,
        "frames_per_min": frames_per_min,
        "camera_count": len(cameras),
        "total_errors": total_errors,
        "status_counts": status_counts,
        "cameras": cameras,
    }


@router.get("/system/health")
async def get_health(_current_user: User = Depends(get_current_user)):
    """Lightweight host-level CPU / RAM / disk / GPU snapshot for the
    footer.

    Mounted at /api/system/health (what SystemHealthFooter polls). The
    bare /api/health path this used to claim is owned by the uptime
    healthcheck in main.py, which shadowed this route entirely.

    Sampled with psutil. cpu_percent uses interval=None so the call
    returns immediately (uses the value since the last call). The
    frontend polls on a coarse cadence so this stays cheap.

    GPU stats are best-effort. ``nvidia-smi`` is queried with a 1.5s
    timeout when present. NULL on non-NVIDIA hosts and on hosts where
    the binary is not on PATH; the UI hides the GPU pill in that case.
    """
    import psutil

    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    # Disk usage on the storage root the app actually writes to. Falls
    # back to '/' if the configured path does not exist yet.
    storage_path = settings.storage_path if hasattr(settings, "storage_path") else "/"
    disk_target = storage_path
    try:
        import os
        if not os.path.isdir(disk_target):
            disk_target = "/"
    except Exception:
        disk_target = "/"
    disk = psutil.disk_usage(disk_target)
    load_avg = None
    try:
        load_avg = list(psutil.getloadavg())
    except (AttributeError, OSError):
        pass

    gpus = _read_nvidia_smi()

    # Worker liveness rides along on the poll the footer already makes, so
    # the UI can say "nothing is running" instead of "nothing happened
    # yet" - which is what it used to tell users while ingestion was dead.
    workers = {
        "ingestion": await heartbeat.is_alive(heartbeat.INGESTION),
        "perception": await heartbeat.is_alive(heartbeat.PERCEPTION),
    }

    # Functional component health rides along too: a worker can be alive while
    # its pipeline is silently broken (model failed to load, every write
    # crashing). Surface any component reporting FAIL so the dashboard can warn,
    # not only the Settings doctor panel.
    from shared import component_health

    degraded = []
    for comp, label in (
        (component_health.OBSERVATION_WRITER, "Perception output"),
        (component_health.AUDIO_TAGGER, "Sound events (claps)"),
        (component_health.VLM, "AI captioning"),
    ):
        h = await component_health.get(comp)
        if h and h.get("status") == component_health.FAIL:
            degraded.append({"id": comp, "label": label, "detail": h.get("detail", "")})

    return {
        "degraded": degraded,
        "cpu_percent": round(cpu, 1),
        "cpu_count": psutil.cpu_count(logical=True),
        "load_avg": load_avg,
        "workers": workers,
        "mem": {
            "total_bytes": mem.total,
            "used_bytes": mem.used,
            "available_bytes": mem.available,
            "percent": mem.percent,
        },
        "disk": {
            "path": disk_target,
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "percent": disk.percent,
        },
        "gpus": gpus,
    }


def _read_nvidia_smi() -> list[dict] | None:
    """Shell out to nvidia-smi for a tight CSV. Returns None when the
    binary is missing or fails. Cached implicitly on every call so the
    cost is just a fork; ~30ms when the driver is up. Frontend polls
    every 10s so this is fine.
    """
    import shutil
    import subprocess

    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=True,
        ).stdout
    except Exception:
        return None
    rows: list[dict] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            rows.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "util_percent": float(parts[2]),
                    "mem_total_mb": float(parts[3]),
                    "mem_used_mb": float(parts[4]),
                    "temp_c": float(parts[5]),
                }
            )
        except ValueError:
            continue
    return rows or None


@router.get("/smtp")
async def get_smtp_config(_current_user: User = Depends(require_admin)):
    """Effective SMTP configuration (in-app settings win over env vars)
    with the password masked. ``source`` tells the UI whether the config
    is editable in-app ("db"), env-managed ("env"), or absent."""
    from shared.email import resolve_smtp

    cfg = await resolve_smtp()
    pw = cfg["password"]
    masked_password = (pw[:2] + "***" + pw[-2:] if len(pw) >= 4 else "***") if pw else ""
    return {
        "smtp_host": cfg["host"],
        "smtp_port": cfg["port"],
        "smtp_user": cfg["user"],
        "smtp_password": masked_password,
        "smtp_from": cfg["from_addr"],
        "smtp_tls": cfg["tls"],
        "source": cfg["source"],
    }


class SmtpConfigBody(BaseModel):
    host: str
    port: int = 587
    user: str = ""
    # Empty string means "keep the currently stored password".
    password: str = ""
    from_addr: str = ""
    tls: bool = True


@router.put("/smtp")
async def put_smtp_config(
    body: SmtpConfigBody, _current_user: User = Depends(require_admin)
):
    """Save SMTP config from the Settings UI. Stored in app settings
    (password Fernet-sealed), effective immediately, no restart. An empty
    host clears the in-app config and falls back to env vars."""
    from shared.app_settings import get_setting, set_setting
    from shared.crypto import encrypt_secret

    host = body.host.strip()
    if not host:
        await set_setting("smtp_config", None)
        return {"ok": True, "source": "env" if settings.smtp_host else "unconfigured"}

    existing = await get_setting("smtp_config")
    password_enc = (existing or {}).get("password_enc", "") if isinstance(existing, dict) else ""
    if body.password:
        password_enc = encrypt_secret(body.password).decode("utf-8")
    await set_setting(
        "smtp_config",
        {
            "host": host,
            "port": int(body.port),
            "user": body.user.strip(),
            "password_enc": password_enc,
            "from": body.from_addr.strip(),
            "tls": bool(body.tls),
        },
    )
    return {"ok": True, "source": "db"}


class SmtpTestRequest(BaseModel):
    to: str


@router.post("/smtp-test")
async def test_smtp(body: SmtpTestRequest, _current_user: User = Depends(require_admin)):
    """Send a test email to verify SMTP configuration."""
    from shared.email import resolve_smtp

    cfg = await resolve_smtp()
    if not cfg["host"]:
        return {"ok": False, "message": "SMTP not configured. Save your mail server details first, then test."}

    try:
        await send_email(
            to=body.to,
            subject="Nurby SMTP Test",
            body="This is a test email from Nurby. Your SMTP configuration is working correctly.",
        )
        return {"ok": True, "message": f"Test email sent to {body.to}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


# ── Runtime app settings ──
#
# Whitelisted, safe-to-expose runtime flags. GET is auth-only and
# returns the merged value (override falls through to DEFAULTS). PATCH
# is admin-only and accepts a partial body. Any unknown key on PATCH
# is rejected with 400 so the surface stays narrow and audit-friendly.

@router.get("/system/setup-checklist")
async def get_setup_checklist(
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Aggregate state for the durable dashboard setup-checklist card.

    Replaces the one-shot wizard as the surface that tells a new install
    what is still missing: a real camera, an AI provider, an active rule,
    and at least one notification channel."""
    from services.api.routes.cameras import resolve_demo_video_url
    from shared.app_settings import get_setting
    from shared.email import resolve_smtp
    from shared.models import Provider, Rule, TelegramChannel, WebhookSubscription

    cameras = (await db.execute(select(Camera.stream_type, Camera.stream_url))).all()
    demo_url = resolve_demo_video_url()
    real_cameras = [
        c for c in cameras if not (c.stream_type == "file" and c.stream_url == demo_url)
    ]

    provider_count = await db.scalar(
        select(func.count()).select_from(Provider).where(Provider.active.is_(True))
    )
    rule_count = await db.scalar(
        select(func.count()).select_from(Rule).where(Rule.enabled.is_(True))
    )

    channels: list[str] = []
    telegram_count = await db.scalar(
        select(func.count()).select_from(TelegramChannel).where(TelegramChannel.enabled.is_(True))
    )
    if telegram_count:
        channels.append("telegram")
    smtp_cfg = await resolve_smtp()
    if smtp_cfg.get("host") and smtp_cfg.get("from_addr"):
        channels.append("smtp")
    webhook_count = await db.scalar(select(func.count()).select_from(WebhookSubscription))
    if webhook_count:
        channels.append("webhook_subscription")

    return {
        "camera_added": {"done": len(cameras) > 0, "demo_only": bool(cameras) and not real_cameras},
        "provider_connected": {"done": bool(provider_count)},
        "first_rule_active": {"done": bool(rule_count)},
        "notifications_configured": {"done": bool(channels), "channels": channels},
        "dismissed": bool(await get_setting("setup_checklist_dismissed", False)),
    }


SETTINGS_WHITELIST: tuple[str, ...] = (
    "system_timezone",
    "journey_idle_seconds",
    "daily_digest_enabled",
    "daily_digest_hour",
    "nudity_blur",
    "webhook_block_private_networks",
    "detect_classes",
    "audio_events",
    "body_reid_tentative_decay_days",
    "cluster_naming_min_sightings",
    "public_base_url",
    "rules_cooldown_backend",
    "onboarding_dismissed",
    "setup_checklist_dismissed",
    "vlm_enrichment_enabled",
    "vlm_enrichment_budget_minutes_per_hour",
    "vehicle_appearance_match_min_similarity",
    "guardian_enabled",
    "guardian_free_delay_seconds",
    "guardian_free_image_interval_seconds",
    "guardian_reveal_min_confidence",
    "guardian_max_cameras_per_person",
    "guardian_pickup_detection_enabled",
    "guardian_pickup_window_seconds",
    "guardian_image_blur_radius",
    "guardian_fall_detection_enabled",
    "guardian_fall_vlm_confirm_enabled",
    "guardian_meal_tracking_enabled",
    "guardian_actions_enabled",
    "guardian_har_enabled",
    "har_cadence_fps",
    "har_segment_retention_days",
    "guardian_har_test_mode",
    "har_action_set",
    "guardian_reveal_enabled",
    "guardian_reveal_ref_distance",
    "guardian_clips_enabled",
    "guardian_clip_blur_sigma",
    "guardian_unblurred_clips_enabled",
    "guardian_require_consent",
    "guardian_app_base_url",
    # FindAnything / visual grounding.
    "grounding_enabled",
    "grounding_backend",
    "grounding_remote_url",
    # Mobile push (FCM). The service account is write-only: it is
    # PATCHable here but never echoed back (absent from
    # SystemSettingsResponse), because it contains a private key.
    "push_fcm_service_account",
    "push_firebase_client_config",
)


def _validate_timezone(tz: str | None) -> None:
    """Reject anything zoneinfo can't resolve. None is allowed and
    means "use the host locale" (consumed downstream)."""
    if tz is None:
        return
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid timezone")


async def _read_whitelisted_settings() -> dict[str, object]:
    """Pull every whitelisted key via ``get_setting`` so DEFAULTS act
    as the floor. ``public_base_url`` additionally falls back to the
    env config so deployments that only configured the env still see
    a value from the API."""
    from shared.app_settings import DEFAULTS, get_setting

    out: dict[str, object] = {}
    for key in SETTINGS_WHITELIST:
        val = await get_setting(key, DEFAULTS.get(key))
        if key == "public_base_url" and not val:
            val = settings.public_base_url or None
        out[key] = val
    return out


@router.get("/system/settings", response_model=SystemSettingsResponse)
async def get_settings(_current_user: User = Depends(get_current_user)) -> SystemSettingsResponse:
    """Return the whitelisted runtime flags. Auth required.

    Path is /api/system/settings (router mounts at /api). Every frontend
    caller (settings page, dashboard onboarding check, wizard dismissal,
    rule-builder timezone hint) uses this path; the route previously sat
    at /api/settings and silently 404'd all of them.
    """
    data = await _read_whitelisted_settings()
    return SystemSettingsResponse(**data)


@router.patch("/system/settings", response_model=SystemSettingsResponse)
async def patch_settings(
    body: SystemSettingsUpdate,
    _current_user: User = Depends(require_admin),
) -> SystemSettingsResponse:
    """Admin-only partial update. Unknown keys 400. Bad timezone 400."""
    from shared.app_settings import set_setting

    # Pydantic already rejects unknown keys (model_config below), but
    # we also defensively check against the whitelist so a future
    # accidental schema addition can't widen the public surface.
    updates = body.model_dump(exclude_unset=True)
    for key in updates:
        if key not in SETTINGS_WHITELIST:
            raise HTTPException(status_code=400, detail="Unknown setting key")

    if "system_timezone" in updates:
        _validate_timezone(updates["system_timezone"])

    for k, v in updates.items():
        await set_setting(k, v)

    data = await _read_whitelisted_settings()
    return SystemSettingsResponse(**data)


# ── Version + updates ──
#
# /system/version reports the running version and checks GitHub for a
# newer release (cached). /system/update is the one-click trigger. it
# only acts when the optional updater sidecar is enabled, otherwise it
# returns the manual instruction so the surface stays safe by default.

import os

_GITHUB_REPO = os.environ.get("NURBY_GITHUB_REPO", "Eshpelin/nurby")
# A path on a shared volume the updater sidecar watches. Writing it asks
# the host to update. Only meaningful when NURBY_SELF_UPDATE is enabled
# and the updater service is running.
_UPDATE_TRIGGER = os.environ.get("NURBY_UPDATE_TRIGGER", "/data/update.request")
_GH_CACHE: dict[str, object] = {"at": 0.0, "latest": None, "url": None}


@router.get("/system/version")
async def get_version(_current_user: User = Depends(get_current_user)):
    """Current version plus the latest GitHub release, if newer."""
    import httpx

    from shared.version import build_sha, current_version, is_newer

    cur = current_version()
    now = time.time()
    error = None

    if not _GH_CACHE["latest"] or now - float(_GH_CACHE["at"]) > 3600:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(
                    f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest",
                    headers={"Accept": "application/vnd.github+json"},
                )
            if resp.status_code == 200:
                j = resp.json()
                _GH_CACHE["latest"] = (j.get("tag_name") or "").lstrip("v") or None
                _GH_CACHE["url"] = j.get("html_url")
                _GH_CACHE["at"] = now
            elif resp.status_code == 404:
                # No releases published yet. not an error worth surfacing.
                _GH_CACHE["at"] = now
            else:
                error = "GitHub returned an unexpected status"
        except Exception:
            error = "Could not reach GitHub to check for updates"

    latest = _GH_CACHE["latest"]
    update_available = bool(latest) and is_newer(str(latest), cur)
    self_update = os.environ.get("NURBY_SELF_UPDATE", "").lower() in ("1", "true", "yes")

    return {
        "current": cur,
        "build": build_sha(),
        "latest": latest,
        "release_url": _GH_CACHE["url"],
        "update_available": update_available,
        "self_update_enabled": self_update,
        "repo": _GITHUB_REPO,
        "error": error,
    }


@router.post("/system/update")
async def trigger_update(_current_user: User = Depends(require_admin)):
    """Ask the host to update to the latest release. Admin only.

    Works only when the optional updater sidecar is enabled
    (NURBY_SELF_UPDATE=1 and the updater service running). Otherwise it
    returns the manual command so nothing privileged happens by default.
    """
    self_update = os.environ.get("NURBY_SELF_UPDATE", "").lower() in ("1", "true", "yes")
    if not self_update:
        return {
            "started": False,
            "self_update_enabled": False,
            "message": "One-click update is not enabled. On the host run. ./scripts/update.sh",
        }
    def _write_trigger() -> None:
        os.makedirs(os.path.dirname(_UPDATE_TRIGGER), exist_ok=True)
        with open(_UPDATE_TRIGGER, "w", encoding="utf-8") as f:
            f.write(str(time.time()))

    try:
        await asyncio.to_thread(_write_trigger)
    except OSError as exc:
        return {"started": False, "self_update_enabled": True, "message": f"Could not signal the updater. {exc}"}
    return {
        "started": True,
        "self_update_enabled": True,
        "message": (
            "Update started. The stack will pull, rebuild, run migrations, and restart."
            " This page will be briefly unavailable."
        ),
    }
