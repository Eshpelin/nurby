"""System status and storage reporting.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from pydantic import BaseModel


# ── System schemas ──

class SystemStatus(BaseModel):
    version: str
    cameras_total: int
    cameras_online: int
    cameras_recording: int
    uptime_seconds: float


class CameraStorageStats(BaseModel):
    camera_id: uuid.UUID
    camera_name: str
    recording_count: int
    recording_bytes: int
    observation_count: int
    retention_mode: str
    retention_days: int
    retention_gb: float


class StorageResponse(BaseModel):
    cameras: list[CameraStorageStats]
    total_recording_bytes: int
    total_observations: int
