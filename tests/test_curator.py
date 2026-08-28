"""Curated household facts and the invariants around them (issue #141).

The orientation block was built from live state, so it could only say
what a query returned right now. It could not hold a distilled habit,
which is the kind of knowledge that prevents a wrong answer before a tool
is called.

The invariants are the valuable part of this feature, and they are what
these tests are mostly about: never touch what a person wrote, never
delete, pinned bypasses everything, rejection is permanent.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.agent.curator import (
    DEFAULT_STALE_DAYS,
    Curator,
    fact_from_association,
    may_modify,
    merge_fact,
    should_archive,
)
from services.agent.household_context import format_household_context

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _fact(**kw):
    base = dict(
        text="Ahmed usually uses the Harrier around 08:00.",
        subject_key="assoc:1",
        kind="habit",
        source="agent",
        status="established",
        pinned=False,
        evidence_count=5,
        last_confirmed_at=NOW - timedelta(days=1),
        archived_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _edge(**kw):
    base = dict(
        id="e-1",
        subject_key="Ahmed",
        object_key="v-1",
        object_label="Harrier",
        relation="uses",
        source="learned",
        status="established",
        distinct_days=30,
        hour_histogram={"8": 28, "9": 2},
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---- the invariants ------------------------------------------------------


def test_a_fact_a_person_wrote_is_never_touched():
    assert may_modify(_fact(source="user")) is False


def test_a_rejected_fact_is_never_revived():
    """The difference between a system that learns and one that nags."""
    assert may_modify(_fact(status="rejected")) is False

    fact = _fact(status="rejected", evidence_count=0)
    assert merge_fact(fact, "new wording", NOW) is False
    assert fact.status == "rejected"
    assert fact.evidence_count == 0


def test_a_pinned_fact_bypasses_everything():
    pinned = _fact(pinned=True, last_confirmed_at=NOW - timedelta(days=999))
    assert may_modify(pinned) is False
    assert should_archive(pinned, NOW) is False


def test_agent_facts_are_modifiable():
    assert may_modify(_fact()) is True


# ---- archive, never delete ----------------------------------------------


def test_a_stale_fact_is_archived_not_deleted():
    stale = _fact(last_confirmed_at=NOW - timedelta(days=DEFAULT_STALE_DAYS + 1))
    assert should_archive(stale, NOW) is True


def test_a_recent_fact_survives():
    assert should_archive(_fact(), NOW) is False


def test_a_habit_can_pause_for_a_holiday():
    """45 days is long on purpose. A household habit stopping for three
    weeks does not stop being true."""
    paused = _fact(last_confirmed_at=NOW - timedelta(days=21))
    assert should_archive(paused, NOW) is False


def test_an_archived_fact_returns_as_a_candidate():
    """The household archived it for a reason, so seeing it once more is
    not enough to state it as established again."""
    archived = _fact(status="archived", archived_at=NOW - timedelta(days=1))
    assert merge_fact(archived, "same fact", NOW) is True
    assert archived.status == "candidate"
    assert archived.archived_at is None


def test_a_candidate_becomes_established_on_more_evidence():
    candidate = _fact(status="candidate", evidence_count=1)
    merge_fact(candidate, "text", NOW)
    assert candidate.status == "established"
    assert candidate.evidence_count == 2
    assert candidate.last_confirmed_at == NOW


def test_only_established_facts_are_archived():
    assert should_archive(_fact(status="candidate"), NOW + timedelta(days=999)) is False


# ---- what becomes a fact -------------------------------------------------


def test_an_established_edge_becomes_a_fact():
    key, text = fact_from_association(_edge())

    assert key == "assoc:e-1"
    assert "Ahmed usually uses Harrier" in text
    assert "08:00" in text
    assert "30 separate days" in text


def test_a_candidate_edge_is_not_a_fact_yet():
    assert fact_from_association(_edge(status="candidate")) is None


def test_a_declared_edge_is_policy_not_habit():
    """An authorization is not something to state as what usually
    happens."""
    assert fact_from_association(_edge(source="declared")) is None


def test_phrasing_works_without_a_model():
    """Deterministic, so a household with no model configured still gets
    its orientation. An auxiliary model may improve the wording later,
    but it never decides whether the fact is true."""
    _, text = fact_from_association(_edge(hour_histogram={}))
    assert text.startswith("Ahmed usually uses Harrier")
    assert "around" not in text


# ---- the orientation block ----------------------------------------------


def _cameras():
    return [{"name": "Back Door", "role": "entry", "location": None, "habits": None}]


def test_facts_reach_the_orientation_block():
    block = format_household_context(
        _cameras(), [], [], None, ["The cat is usually on the Back Door at night."],
    )
    assert "The cat is usually on the Back Door at night." in block


def test_facts_are_labelled_as_distilled_and_possibly_stale():
    """They are not evidence, and the block has to say so."""
    block = format_household_context(_cameras(), [], [], None, ["A fact."])
    assert "distilled, may be stale" in block


def test_the_block_still_renders_without_facts():
    block = format_household_context(_cameras(), [], [], None, None)
    assert "Learned about this household" not in block
    assert "Cameras:" in block


# ---- scheduling ----------------------------------------------------------


def test_the_first_pass_is_due_immediately():
    assert Curator().due(NOW, 12) is True


def test_a_pass_is_not_repeated_inside_its_interval():
    curator = Curator()
    curator._last_run = NOW - timedelta(hours=1)
    assert curator.due(NOW, 12) is False


def test_a_pass_is_due_again_after_the_interval():
    curator = Curator()
    curator._last_run = NOW - timedelta(hours=13)
    assert curator.due(NOW, 12) is True
