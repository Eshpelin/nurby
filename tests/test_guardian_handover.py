"""Inferred pickup vs staff-confirmed handover (#191).

Guardian infers an escort from co-present people and vehicle plates and can
match the approved-pickup registry. None of that is a completed handover. These
tests pin the distinction end to end:

  - The pure state contract: a match is at most ``approved_match``, never
    ``confirmed``; only an explicit staff decision reaches ``confirmed``.
  - The alert wording: an inferred pickup never says "confirmed by staff".
  - The emit seam: a fresh pickup event is born inferred.
  - The API: confirmation records who/when/evidence and a correction appends to
    the history rather than erasing it; a non-pickup event cannot be confirmed.

Handlers run directly against a stubbed AsyncSession, the DB-free convention of
the suite (see tests/test_verified_activation.py).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from services.api.routes import guardian as g
from services.guardian import alerts as alerts_mod
from services.guardian import entitlements as ent
from services.guardian import handover as ho
from shared.models import GuardianHandoverConfirmation

T0 = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.run(coro)


# ── pure state contract ──────────────────────────────────────────────

def test_match_is_only_approved_never_confirmed():
    assert ho.inferred_state(True) == ho.APPROVED_MATCH
    assert ho.inferred_state(False) == ho.POSSIBLE
    assert ho.inferred_state(None) == ho.POSSIBLE
    # Inference never produces a staff-confirmed state.
    assert ho.inferred_state(True) != ho.CONFIRMED
    assert ho.is_staff_confirmed(ho.APPROVED_MATCH) is False
    assert ho.is_staff_confirmed(ho.POSSIBLE) is False
    assert ho.is_staff_confirmed(ho.CONFIRMED) is True


def test_legacy_row_without_state_reads_as_inferred():
    # An old pickup row (handover_state is None) is never treated as confirmed.
    assert ho.normalize_state(None, True) == ho.APPROVED_MATCH
    assert ho.normalize_state(None, False) == ho.POSSIBLE
    assert ho.is_staff_confirmed(ho.normalize_state(None, True)) is False


def test_apply_decision_rejects_smuggled_inferred_state():
    assert ho.apply_decision("confirmed") == ho.CONFIRMED
    assert ho.apply_decision("corrected") == ho.CORRECTED
    for bad in ("possible", "approved_match", "handover", ""):
        with pytest.raises(ValueError):
            ho.apply_decision(bad)


# ── alert wording ────────────────────────────────────────────────────

def _pickup_msg(**kw):
    return alerts_mod.compose_message("picked_up", "Mia", **kw)


def test_copresence_alone_never_says_confirmed():
    # Ambiguous: someone nearby, no registry match.
    msg = _pickup_msg(pickup_matched=False, handover_state=ho.POSSIBLE)
    assert "confirmed by staff" not in msg.lower() or "not been confirmed" in msg.lower()
    assert "has not been confirmed by staff" in msg.lower()


def test_plate_match_alone_never_says_confirmed():
    msg = _pickup_msg(pickup_matched=True, approved_name="Dad", handover_state=ho.APPROVED_MATCH)
    assert "matches Dad's" in msg
    assert "has not been confirmed by staff" in msg.lower()
    assert "Pickup confirmed by staff" not in msg


def test_confirmed_state_reads_as_staff_confirmed():
    msg = _pickup_msg(pickup_matched=True, approved_name="Dad", handover_state=ho.CONFIRMED)
    assert msg.startswith("Pickup confirmed by staff")
    assert "Dad" in msg


def test_corrected_state_reads_as_correction():
    msg = _pickup_msg(pickup_matched=True, approved_name="Dad", handover_state=ho.CORRECTED)
    assert "corrected by staff" in msg
    assert "No confirmed handover" in msg


def test_absent_state_defaults_to_inferred_wording():
    # No handover_state passed at all still must not claim confirmation.
    msg = _pickup_msg(pickup_matched=True, approved_name="Dad")
    assert "has not been confirmed by staff" in msg.lower()


# ── expired-grant: an expired link receives no alert at all ───────────

def _link(**kw):
    base = dict(
        id=uuid.uuid4(), guardian_user_id=uuid.uuid4(), tier="full",
        revoked_at=None, expires_at=None, alert_prefs=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_expired_grant_is_not_a_pickup_recipient():
    active = _link()
    expired = _link(expires_at=T0 - timedelta(hours=1))
    revoked = _link(revoked_at=T0 - timedelta(hours=1))
    got = alerts_mod.recipients_for([active, expired, revoked], "picked_up", now=T0)
    assert active in got
    assert expired not in got and revoked not in got
    # Sanity: the inactive links really are inactive under the same clock.
    assert ent.is_active(expired, T0) is False


# ── emit seam: a pickup event is born inferred, never confirmed ───────

class _EmitDB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.add = MagicMock(side_effect=self.added.append)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


def _emit_event(pickup):
    from shared.models import GuardianEvent

    db = _EmitDB()
    person = SimpleNamespace(id=uuid.uuid4(), display_name="Mia", nickname=None)
    link = _link()
    _run(alerts_mod.emit(db, person, "picked_up", [link], pickup=pickup, now=T0))
    events = [o for o in db.added if isinstance(o, GuardianEvent)]
    assert len(events) == 1
    return events[0]


def test_emit_plate_match_stores_approved_not_confirmed():
    ev = _emit_event({"matched": True, "approved_name": "Dad", "by": "vehicle"})
    assert ev.handover_state == ho.APPROVED_MATCH
    assert ho.is_staff_confirmed(ev.handover_state) is False


def test_emit_unmatched_stores_possible():
    ev = _emit_event({"matched": False, "approved_name": None, "by": None})
    assert ev.handover_state == ho.POSSIBLE


# ── API: staff confirmation + correction with an audit trail ──────────

class _Admin:
    def __init__(self):
        self.id = uuid.uuid4()
        self.role = "admin"


class _HandoverDB:
    """Stub AsyncSession for the handover endpoints.

    ``rows`` maps (Model, id) -> object for db.get. The history query returns
    every confirmation added so far, oldest first, like the real ascending
    ``order_by``.
    """

    def __init__(self, rows):
        self.rows = dict(rows)
        self.confirmations = []
        self.commits = 0

        def _add(obj):
            if isinstance(obj, GuardianHandoverConfirmation):
                self.confirmations.append(obj)
        self.add = MagicMock(side_effect=_add)

    async def get(self, model, ident):
        return self.rows.get((model, ident))

    async def execute(self, _stmt):
        res = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = list(self.confirmations)
        res.scalars.return_value = scalars
        return res

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


def _pickup_event(**kw):
    from shared.models import GuardianEvent, Person

    base = dict(
        id=uuid.uuid4(), person_id=uuid.uuid4(), kind="picked_up",
        pickup_matched=True, pickup_name="Dad", handover_state=ho.APPROVED_MATCH,
    )
    base.update(kw)
    event = SimpleNamespace(**base)
    person = SimpleNamespace(id=event.person_id, display_name="Mia", nickname=None)
    db = _HandoverDB({(GuardianEvent, event.id): event, (Person, event.person_id): person})
    return event, db


def _confirm(db, event, admin, decision, **kw):
    from shared.schemas import HandoverConfirmRequest

    body = HandoverConfirmRequest(decision=decision, **kw)
    return _run(g.confirm_handover(event_id=event.id, body=body, admin=admin, db=db))


def test_confirm_records_who_when_and_sets_confirmed():
    event, db = _pickup_event()
    admin = _Admin()
    view = _confirm(db, event, admin, "confirmed", note="I walked them out", evidence={"clip": "c1"})
    assert view.handover_state == ho.CONFIRMED
    assert view.staff_confirmed is True
    assert event.handover_state == ho.CONFIRMED
    # One audit row: who, evidence, prior state, and it was committed.
    assert len(db.confirmations) == 1
    row = db.confirmations[0]
    assert row.confirmed_by_user_id == admin.id
    assert row.decision == ho.CONFIRMED
    assert row.prior_state == ho.APPROVED_MATCH
    assert row.evidence == {"clip": "c1"} and row.note == "I walked them out"
    assert db.commits == 1
    assert "Pickup confirmed by staff" in view.message


def test_correction_appends_and_retains_history():
    event, db = _pickup_event()
    _confirm(db, event, _Admin(), "confirmed")
    # A different staffer later corrects it. The earlier decision is kept.
    corrector = _Admin()
    view = _confirm(db, event, corrector, "corrected", note="wrong child")
    assert view.handover_state == ho.CORRECTED
    assert view.staff_confirmed is False
    assert len(db.confirmations) == 2
    assert [c.decision for c in db.confirmations] == [ho.CONFIRMED, ho.CORRECTED]
    # The correction row remembers what it overrode.
    assert db.confirmations[1].prior_state == ho.CONFIRMED
    # The response surfaces the whole trail in order.
    assert [h.decision for h in view.history] == [ho.CONFIRMED, ho.CORRECTED]


def test_get_handover_reads_state_without_confirming():
    event, db = _pickup_event(handover_state=ho.POSSIBLE, pickup_matched=False)
    view = _run(g.get_handover(event_id=event.id, admin=_Admin(), db=db))
    assert view.handover_state == ho.POSSIBLE
    assert view.staff_confirmed is False
    assert db.confirmations == [] and db.commits == 0
    assert "has not been confirmed by staff" in view.message.lower()


def test_non_pickup_event_cannot_be_confirmed():
    from shared.models import GuardianEvent, Person

    event = SimpleNamespace(id=uuid.uuid4(), person_id=uuid.uuid4(), kind="arrived",
                            pickup_matched=None, pickup_name=None, handover_state=None)
    person = SimpleNamespace(id=event.person_id, display_name="Mia", nickname=None)
    db = _HandoverDB({(GuardianEvent, event.id): event, (Person, event.person_id): person})
    with pytest.raises(HTTPException) as ei:
        _confirm(db, event, _Admin(), "confirmed")
    assert ei.value.status_code == 400
    assert db.confirmations == [] and db.commits == 0


def test_confirm_missing_event_is_404():
    from shared.models import GuardianEvent

    db = _HandoverDB({})
    body_event = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(HTTPException) as ei:
        _confirm(db, body_event, _Admin(), "confirmed")
    assert ei.value.status_code == 404
    assert (GuardianEvent, body_event.id) not in db.rows
