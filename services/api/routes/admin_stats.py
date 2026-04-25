"""Admin-only system stats. Exposes the in-process metrics snapshot.

Auth-gated so household members cannot scrape per-camera throughput
counters that would let them infer when audio is hot.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from services.perception.audio import metrics as audio_metrics
from shared.auth import get_current_user
from shared.models import User

router = APIRouter()


@router.get("/stats")
async def get_stats(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {
        "audio": audio_metrics.snapshot(),
    }
