"""Pickup evidence states: telling an inferred pickup from a confirmed handover.

Guardian infers an escort from co-present people and vehicle plates near a
departure and can match that against the approved-pickup registry. Neither a
co-presence nor a plate match establishes that an authorized guardian actually
took custody. Only an explicit action by authorized facility staff does.

This module is the single source of truth for the four evidence states and the
words shown for each. It is pure so the distinction is fully unit-tested and can
never drift between the API, the alert text and the clients.

States (issue #191, product review 2026-09-16):

    possible        Co-presence or a plate seen near pickup. No registry match.
    approved_match  An approved person/vehicle matched. Still only inferred.
    confirmed       Authorized staff confirmed the handover happened.
    corrected       Staff reviewed and this was NOT a valid handover.

``possible`` and ``approved_match`` are inferred; ``confirmed`` and ``corrected``
are staff decisions. Inference alone never yields ``confirmed``.
"""

from __future__ import annotations

POSSIBLE = "possible"
APPROVED_MATCH = "approved_match"
CONFIRMED = "confirmed"
CORRECTED = "corrected"

# The states a camera inference may produce on its own. Never ``confirmed``.
INFERRED_STATES = (POSSIBLE, APPROVED_MATCH)
# The states only an authorized staff action may set.
STAFF_STATES = (CONFIRMED, CORRECTED)
ALL_STATES = INFERRED_STATES + STAFF_STATES

# The decisions the confirmation endpoint accepts.
DECISIONS = (CONFIRMED, CORRECTED)

# Short UI words per state. Kept beside the contract, served to the clients.
STATE_LABELS = {
    POSSIBLE: "Possible pickup detected",
    APPROVED_MATCH: "Approved person/vehicle matched",
    CONFIRMED: "Pickup confirmed by staff",
    CORRECTED: "Correction: not a confirmed handover",
}


def inferred_state(pickup_matched: bool | None) -> str:
    """The evidence state a fresh pickup inference carries.

    A registry match is ``approved_match``; anything else is ``possible``. This
    is the ceiling for automated inference. It is never ``confirmed``.
    """
    return APPROVED_MATCH if pickup_matched else POSSIBLE


def is_staff_confirmed(state: str | None) -> bool:
    """True only when authorized staff explicitly confirmed the handover."""
    return state == CONFIRMED


def is_inferred(state: str | None) -> bool:
    """True for a camera-only state that no staff member has ruled on."""
    return state in INFERRED_STATES or state is None


def normalize_state(state: str | None, pickup_matched: bool | None = None) -> str:
    """Coerce a stored/absent state into a known one.

    Legacy rows persisted before this feature have no ``handover_state``; fall
    back to what the pickup match implies so they read as inferred, never
    confirmed.
    """
    if state in ALL_STATES:
        return state
    return inferred_state(pickup_matched)


def apply_decision(decision: str) -> str:
    """Map a staff decision to the resulting event state.

    Raises ``ValueError`` for anything outside :data:`DECISIONS` so a bad
    request can never smuggle in an inferred state as if it were a decision.
    """
    if decision not in DECISIONS:
        raise ValueError(f"unknown handover decision: {decision!r}")
    return decision


def state_label(state: str | None, pickup_matched: bool | None = None) -> str:
    return STATE_LABELS[normalize_state(state, pickup_matched)]
