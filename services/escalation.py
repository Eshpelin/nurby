"""Pick a stronger model for a step that already failed its quality check.

crush lets a person switch models mid-session while keeping the context. Nurby
picked one provider per agent run and per VLM pass and was stuck with it: when
a cheap local model failed its own verify round or burned every turn without
converging, there was no way to retry that one step on something better
(issue #132).

This module answers one question: given the provider a step just failed on,
which provider should the retry use? It is used at the two points where quality
is already measured, and nowhere else. Escalation without a failure signal is
just spending money.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from shared.app_settings import get_setting
from shared.models import Provider

logger = logging.getLogger("nurby.escalation")

# Rough capability order, weakest last. Only used when no escalation provider
# is configured explicitly. Local models sit at the bottom not because they
# are bad but because a household running one is running it on a machine that
# also has to keep decoding video.
KIND_RANK = {
    "anthropic": 0,
    "openai": 1,
    "gemini": 2,
    "google": 2,
    "ollama": 9,
}
UNKNOWN_RANK = 5


def provider_rank(provider) -> int:
    """Position in KIND_RANK, lower is stronger. Pure, for tests."""
    return KIND_RANK.get((getattr(provider, "kind", "") or "").lower(), UNKNOWN_RANK)


def pick_stronger(current, candidates: list) -> object | None:
    """The best candidate strictly stronger than ``current``, or None.

    Ties do not count: retrying the same tier is a second roll of the same
    dice, and the caller has already paid for one failure. Candidates without
    a usable model are skipped. Pure, for tests."""
    current_rank = provider_rank(current) if current is not None else UNKNOWN_RANK
    current_id = getattr(current, "id", None)
    best = None
    for cand in candidates or []:
        if getattr(cand, "id", None) == current_id:
            continue
        if not getattr(cand, "default_model", None):
            continue
        if provider_rank(cand) >= current_rank:
            continue
        if best is None or provider_rank(cand) < provider_rank(best):
            best = cand
    return best


async def escalation_provider(db, current, setting_key: str):
    """The provider to retry a failed step on, or None to not retry.

    ``setting_key`` names an optional admin override holding a provider id.
    When it is set and resolves to an active provider other than the current
    one, that provider wins outright: an admin saying "escalate to this" beats
    a built-in ranking. Otherwise the strongest active provider above the
    current one is used, and None means there is nothing better available, so
    the caller keeps the result it already has."""
    try:
        override = await get_setting(setting_key)
        if override:
            try:
                chosen = await db.get(Provider, uuid.UUID(str(override)))
            except (ValueError, TypeError):
                chosen = None
            if (
                chosen is not None
                and getattr(chosen, "active", False)
                and chosen.default_model
                and chosen.id != getattr(current, "id", None)
            ):
                return chosen

        candidates = (await db.execute(
            select(Provider).where(Provider.active.is_(True))
        )).scalars().all()
        return pick_stronger(current, candidates)
    except Exception:
        logger.debug("escalation lookup failed", exc_info=True)
        return None
