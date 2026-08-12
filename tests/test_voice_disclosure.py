"""What a camera may say to a stranger (issue #157).

The failure this guards against is not "the agent said something odd", it
is "the agent told someone useful something about this household". Every
refusal here is one of those, so the refusals matter far more than the
approvals and are tested accordingly.
"""

import pytest

from services.voice.disclosure import (
    MAX_REPLY_CHARS,
    SAFE_FALLBACK,
    check_reply,
    contains_household_name,
    safe_reply,
)


def _refused(text, **kw):
    return check_reply(text, **kw)


# ---- absence: the worst thing this feature could say ---------------------


@pytest.mark.parametrize("line", [
    "Nobody is home right now.",
    "Nobody's home at the moment.",
    "No one is home, sorry.",
    "There's no one here.",
    "The house is empty until later.",
    "They're not home right now.",
    "He isn't home.",
    "She's out at the moment.",
    "They are away this week.",
    "I'm home alone.",
])
def test_absence_is_always_refused(line):
    verdict = _refused(line)
    assert verdict.allowed is False
    assert verdict.reason == "absence"


def test_absence_cannot_be_unlocked_by_any_setting():
    """No household configuration should be able to make this sayable."""
    verdict = _refused(
        "Nobody is home.",
        may_confirm=["absence", "schedule", "names", "everything"],
    )
    assert verdict.allowed is False


def test_curly_apostrophes_do_not_slip_through():
    """Models emit typographic quotes constantly."""
    assert _refused("Nobody’s home.").allowed is False


def test_padded_whitespace_does_not_slip_through():
    assert _refused("nobody   is    home").allowed is False


# ---- schedule ------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "She'll be back on Tuesday.",
    "They will be home around six.",
    "He gets home at five.",
])
def test_schedule_is_refused_by_default(line):
    assert _refused(line).reason == "schedule"


def test_a_line_leaking_both_absence_and_schedule_is_classed_as_absence():
    """"They're away until Monday" is a schedule sentence, but the part
    that matters is the absence. Classing it as absence keeps it refused
    even for a household that opted into schedule disclosure."""
    verdict = _refused("They're away until Monday.", may_confirm=["schedule"])

    assert verdict.reason == "absence"
    assert verdict.allowed is False


def test_schedule_is_the_only_unlockable_rule():
    """A household that genuinely wants "back around six" said aloud can
    opt into it. Nothing else is negotiable."""
    line = "They will be home around six."
    assert _refused(line).allowed is False
    assert _refused(line, may_confirm=["schedule"]).allowed is True


# ---- access --------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "The door is unlocked, come in.",
    "The code is 4821.",
    "The key is under the mat.",
    "There's a spare key round the back.",
    "You can come in.",
    "Just let yourself in.",
    "I'll unlock the door for you.",
    "Leave it inside the house.",
])
def test_anything_that_helps_someone_get_in_is_refused(line):
    assert _refused(line).reason == "access"


def test_access_cannot_be_unlocked_either():
    assert _refused("The code is 1234.", may_confirm=["access"]).allowed is False


# ---- impersonation -------------------------------------------------------


@pytest.mark.parametrize("line", [
    "I'm the owner, what do you need?",
    "I live here.",
    "I'll come down in a second.",
    "I'm on my way.",
])
def test_the_agent_never_implies_a_person_is_present(line):
    assert _refused(line).reason == "impersonation"


# ---- identity ------------------------------------------------------------


def test_greeting_a_resident_by_name_is_refused():
    """Saying "Hi Sarah" out loud tells a stranger both who lives here
    and who is currently home."""
    verdict = _refused("Hi Sarah, welcome back.", household_names=["Sarah", "Ahmed"])
    assert verdict.reason == "identity"
    assert verdict.matched == "Sarah"


def test_confirming_a_surname_to_a_courier_is_refused():
    """The delivery example from the original issue."""
    verdict = _refused(
        "Yes, this is Ahmed Saqib's house.", household_names=["Ahmed Saqib"]
    )
    assert verdict.allowed is False


def test_names_can_be_opted_into():
    verdict = _refused(
        "Hi Sarah.", household_names=["Sarah"], may_confirm=["names"]
    )
    assert verdict.allowed is True


def test_a_name_inside_another_word_is_not_a_match():
    """"Sam" must not fire on "same"."""
    assert contains_household_name("That's the same thing.", ["Sam"]) is None


def test_name_matching_ignores_case():
    assert contains_household_name("hello ahmed", ["Ahmed"]) == "Ahmed"


def test_single_character_names_are_ignored():
    """They would match almost every sentence."""
    assert contains_household_name("Anything at all.", ["A", ""]) is None


def test_no_names_configured_is_survivable():
    assert contains_household_name("Anything", None) is None


# ---- household deny list -------------------------------------------------


def test_a_household_can_add_its_own_forbidden_phrase():
    verdict = _refused("The dog is friendly.", never_say=["the dog"])
    assert verdict.reason == "never_say"


# ---- length and emptiness ------------------------------------------------


def test_an_empty_line_is_refused():
    assert _refused("   ").reason == "empty"


def test_a_rambling_reply_is_refused():
    """A doorstep answer is a sentence or two. Anything longer is the
    model monologuing at a stranger."""
    assert _refused("word " * 200).reason == "too_long"


def test_a_reply_at_the_limit_is_allowed():
    assert _refused("x" * (MAX_REPLY_CHARS - 1)).allowed is True


# ---- what actually gets said --------------------------------------------


def test_an_ordinary_doorstep_reply_passes():
    for line in [
        "Hello, how can I help?",
        "What do you need?",
        "I've let the household know you're here.",
        "You can leave the parcel by the door.",
        "Thanks, I'll pass that on.",
    ]:
        assert check_reply(line).allowed is True, line


def test_a_refused_line_is_replaced_rather_than_dropped():
    """Silence makes a visitor ring again, or conclude the house is
    empty, which is what the refusal was protecting against."""
    spoken, verdict = safe_reply("Nobody is home.")

    assert spoken == SAFE_FALLBACK
    assert verdict.allowed is False


def test_an_allowed_line_is_returned_normalised():
    spoken, verdict = safe_reply("  Hello,   how can I help? ")

    assert spoken == "Hello, how can I help?"
    assert verdict.allowed is True


def test_the_fallback_itself_survives_the_filter():
    """It is spoken in exactly the situations the filter is strictest
    about, so it must not be caught by its own rules."""
    assert check_reply(SAFE_FALLBACK).allowed is True


def test_the_fallback_gives_nothing_away():
    lowered = SAFE_FALLBACK.lower()
    for leak in ("home", "away", "alone", "empty", "out"):
        assert f" {leak} " not in f" {lowered} "
