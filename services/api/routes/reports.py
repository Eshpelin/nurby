"""Scheduled report CRUD + manual run.

A scheduled report is a saved agent question on a clock ("what was Simon
doing all day, every night at 7 PM"). The runner lives in
services/api/report_scheduler.py; POST /{id}/run executes one inline so
a user can preview the output while building it.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.database import get_db
from shared.models import ScheduledReport, User
from shared.schemas import (
    ScheduledReportCreate,
    ScheduledReportResponse,
    ScheduledReportUpdate,
)

router = APIRouter()

_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _validate_days(days: list[str] | None) -> list[str] | None:
    if days is None:
        return None
    cleaned = [d for d in days if d in _VALID_DAYS]
    return cleaned or None


@router.get("", response_model=list[ScheduledReportResponse])
async def list_reports(
    _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(select(ScheduledReport).order_by(ScheduledReport.created_at))
    ).scalars().all()
    return rows


@router.post("", response_model=ScheduledReportResponse, status_code=201)
async def create_report(
    body: ScheduledReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = ScheduledReport(
        **{**body.model_dump(), "days": _validate_days(body.days)},
        created_by_user_id=user.id,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


@router.get("/{report_id}", response_model=ScheduledReportResponse)
async def get_report(
    report_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(ScheduledReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.patch("/{report_id}", response_model=ScheduledReportResponse)
async def update_report(
    report_id: uuid.UUID,
    body: ScheduledReportUpdate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(ScheduledReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    updates = body.model_dump(exclude_unset=True)
    if "days" in updates:
        updates["days"] = _validate_days(updates["days"])
    for field, value in updates.items():
        setattr(report, field, value)
    await db.commit()
    await db.refresh(report)
    return report


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(ScheduledReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    await db.delete(report)
    await db.commit()


@router.post("/{report_id}/run", response_model=ScheduledReportResponse)
async def run_report_now(
    report_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the report inline (agent run + delivery) and return the
    refreshed row. Lets a user preview the output while building it.
    Can take tens of seconds with a slow local model."""
    report = await db.get(ScheduledReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    from services.api.report_scheduler import run_and_deliver

    status, output = await run_and_deliver(report_id)
    if status == "failed":
        raise HTTPException(status_code=502, detail=output or "report run failed")
    await db.refresh(report)
    return report
