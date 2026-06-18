"""Scheduled report runner.

Ticks every minute in the API process (which owns the agent driver) and
runs every due ScheduledReport through the same agent pipeline as Ask
Nurby, then delivers the grounded answer to the configured channels
(in-app notification, email).

Due semantics: a report is due once its local (system_timezone)
hour:minute has passed today, on an allowed day, and it has not already
run for today's slot. Missing a tick (API restart at 19:00) only delays
the report, never skips it: it fires on the next tick after the slot.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from shared.app_settings import get_setting
from shared.database import async_session
from shared.models import Notification, Person, Provider, ScheduledReport, User

logger = logging.getLogger("nurby.api.reports")

TICK_SECONDS = 60
_DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def is_due(report, now_utc: datetime, tz) -> bool:
    """Pure due-check so the scheduling contract is unit-testable.

    True when today's scheduled slot (report.hour:minute in ``tz``) is in
    the past, today is an allowed day, and last_run_at predates the slot.
    """
    if not report.enabled:
        return False
    local_now = now_utc.astimezone(tz)
    if report.days:
        if _DAY_KEYS[local_now.weekday()] not in report.days:
            return False
    slot_local = local_now.replace(
        hour=int(report.hour), minute=int(report.minute), second=0, microsecond=0
    )
    if local_now < slot_local:
        return False
    slot_utc = slot_local.astimezone(timezone.utc)
    last = report.last_run_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last is None or last < slot_utc


def build_question(report, person_name: str | None) -> str:
    """Shape the saved prompt into a report-grade agent question."""
    parts = [report.prompt.strip().rstrip(".") + "."]
    if person_name:
        parts.append(f'Focus on the person known as "{person_name}".')
    parts.append(
        "Cover roughly the last 24 hours. Write the answer as a short,"
        " readable report a person would be glad to receive on their"
        " phone: lead with the most notable thing, use friendly clock"
        " times, group repetitive activity, and say so plainly if"
        " nothing notable happened."
    )
    return " ".join(parts)


async def run_stats_only_report(report_id: uuid.UUID) -> tuple[str, str | None]:
    """Produce a stats-only digest when no AI provider is available.

    Scene narration and Ask Nurby need a provider, but a scheduled report
    should still arrive: the digest generator degrades to a structured,
    provider-free summary (who/when/which camera roll-ups, no LLM prose).
    Returns ("ok", text) on success so the report SUCCEEDS instead of being
    marked failed, keeping the no-provider experience calm and useful.
    """
    from services.search.digest import generate_digest

    async with async_session() as db:
        report = await db.get(ScheduledReport, report_id)
        if report is None:
            return ("failed", "report not found")
        try:
            # provider=None routes generate_digest to its narrative fallback,
            # built from the same roll-ups, with no LLM call.
            digest = await generate_digest(db, period="24h", provider=None)
        except Exception:
            logger.exception("report %s stats-only digest crashed", report_id)
            return ("failed", "stats-only digest crashed; see logs")

    summary = (digest.get("summary") or "").strip()
    if not summary:
        return ("empty", None)
    return ("ok", summary)


async def run_report(report_id: uuid.UUID) -> tuple[str, str | None]:
    """Run one report through the agent now. Returns (status, output).

    status is "ok", "empty", or "failed". Used by both the scheduler tick
    and the manual POST /api/reports/{id}/run endpoint.

    When no usable AI provider is configured the report does not fail: it
    falls back to a stats-only digest so the user still receives their
    scheduled summary (AI prose is optional).
    """
    from services.agent import runs as runs_mod
    from services.agent.driver import AgentDriver

    async with async_session() as db:
        report = await db.get(ScheduledReport, report_id)
        if report is None:
            return ("failed", "report not found")

        user = (
            await db.get(User, report.created_by_user_id)
            if report.created_by_user_id
            else None
        )
        if user is None:
            # Fall back to any active admin so orphaned reports keep running.
            user = (
                await db.execute(
                    select(User).where(User.role == "admin", User.is_active == True)  # noqa: E712
                )
            ).scalars().first()
        if user is None:
            return ("failed", "no active user to attribute the run to")

        provider = None
        if report.provider_id:
            provider = await db.get(Provider, report.provider_id)
        if provider is None or not provider.active:
            default = await get_setting("agent_default_provider_id")
            if default:
                provider = await db.get(Provider, uuid.UUID(str(default)))
        if provider is None or not provider.active:
            # No AI provider: succeed with a stats-only digest instead of
            # failing the scheduled report.
            return await run_stats_only_report(report_id)
        model = provider.default_model
        if not model:
            # Provider exists but cannot run the agent: still deliver stats.
            return await run_stats_only_report(report_id)

        person_name = None
        if report.person_id:
            person = await db.get(Person, report.person_id)
            if person:
                person_name = person.nickname or person.display_name

        question = build_question(report, person_name)
        run = await runs_mod.create_run(
            user_id=user.id,
            question=question,
            provider_id=provider.id,
            model=model,
            parent_run_id=None,
            db=db,
        )
        run_id = run.id

    async def _noop_broadcast(_run_id: str, _payload: dict) -> None:
        return None

    driver = AgentDriver(db_factory=async_session, broadcast=_noop_broadcast)
    try:
        await driver.run(
            run_id=run_id,
            user=user,
            question=question,
            provider=provider,
            model=model,
            parent_run_id=None,
        )
    except Exception:
        logger.exception("report %s agent run crashed", report_id)
        return ("failed", "agent run crashed; see logs")

    async with async_session() as db:
        from shared.models import AgentRun

        run = await db.get(AgentRun, run_id)
        answer = (run.final_answer or "").strip() if run else ""
    if not answer:
        return ("empty", None)
    return ("ok", answer)


async def _deliver(report, answer: str) -> None:
    delivery = report.delivery or {}
    if delivery.get("notify", True):
        try:
            from services.api.ws import broadcast

            async with async_session() as db:
                notif = Notification(
                    message=f"\U0001f4cb {report.name}: {answer}"[:4000],
                    severity="info",
                )
                db.add(notif)
                await db.commit()
                await db.refresh(notif)
            await broadcast(
                {
                    "type": "notification",
                    "id": str(notif.id),
                    "message": notif.message,
                    "severity": "info",
                }
            )
        except Exception:
            logger.exception("report %s in-app delivery failed", report.id)
    email_to = (delivery.get("email") or "").strip()
    if email_to:
        try:
            from shared.email import send_email

            await send_email(
                to=email_to,
                subject=f"Nurby report: {report.name}",
                body=answer,
            )
        except Exception:
            logger.exception("report %s email delivery to %s failed", report.id, email_to)

    tg_channel_raw = (str(delivery.get("telegram_channel_id") or "")).strip()
    if tg_channel_raw:
        try:
            import html as _html

            from services.notify.telegram import TelegramAPI
            from shared.crypto import InvalidToken, decrypt_secret
            from shared.models import TelegramChannel

            async with async_session() as db:
                ch = await db.get(TelegramChannel, uuid.UUID(tg_channel_raw))
                usable = (
                    ch is not None and ch.enabled and ch.paired_at is not None and ch.chat_id
                )
                token = None
                chat_id = None
                if usable:
                    try:
                        token = decrypt_secret(ch.bot_token_enc)
                        chat_id = ch.chat_id
                    except InvalidToken:
                        logger.warning(
                            "report %s telegram channel token unreadable (jwt_secret rotated?)",
                            report.id,
                        )
            if token and chat_id:
                text = (
                    f"\U0001f4cb <b>{_html.escape(report.name)}</b>\n\n"
                    f"{_html.escape(answer)}"
                )[:4000]
                await TelegramAPI.send_message(token, chat_id, text)
            else:
                logger.warning(
                    "report %s telegram delivery skipped: channel missing or unpaired",
                    report.id,
                )
        except Exception:
            logger.exception("report %s telegram delivery failed", report.id)

    webhook_url = (delivery.get("webhook") or "").strip()
    if webhook_url:
        try:
            from services.events.actions import deliver_signed

            ok, detail = await deliver_signed(
                "POST",
                webhook_url,
                {
                    "type": "scheduled_report",
                    "report_id": str(report.id),
                    "name": report.name,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "output": answer,
                },
                secret=(delivery.get("webhook_secret") or None),
            )
            if not ok:
                logger.warning("report %s webhook delivery failed: %s", report.id, detail)
        except Exception:
            logger.exception("report %s webhook delivery failed", report.id)


async def _stamp(report_id: uuid.UUID, status: str, output: str | None) -> None:
    async with async_session() as db:
        report = await db.get(ScheduledReport, report_id)
        if report is None:
            return
        report.last_run_at = datetime.now(timezone.utc)
        report.last_status = status
        if output is not None:
            report.last_output = output
        await db.commit()


async def run_and_deliver(report_id: uuid.UUID) -> tuple[str, str | None]:
    """Run one report and deliver on success. Stamps last_run/status."""
    status, output = await run_report(report_id)
    await _stamp(report_id, status, output if status == "ok" else None)
    if status == "ok" and output:
        async with async_session() as db:
            report = await db.get(ScheduledReport, report_id)
        if report is not None:
            await _deliver(report, output)
    return (status, output)


class ReportScheduler:
    """Minute tick over enabled reports. Started from the API lifespan."""

    def __init__(self):
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        logger.info("Scheduled report runner started")
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("report scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        tz_name = await get_setting("system_timezone") or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            reports = (
                await db.execute(
                    select(ScheduledReport).where(ScheduledReport.enabled == True)  # noqa: E712
                )
            ).scalars().all()
            due = [r.id for r in reports if is_due(r, now, tz)]
        for report_id in due:
            logger.info("running scheduled report %s", report_id)
            try:
                await run_and_deliver(report_id)
            except Exception:
                logger.exception("scheduled report %s failed", report_id)
