"""Turn-taking rules for a spoken exchange (issue #157).

Half duplex and barge-in are the two that bite. A camera shares one audio
path, so while the speaker plays the microphone hears it, and an agent
that transcribes its own voice replies to itself. These pin the timing
that stops that, without stopping a visitor from interrupting.
"""

from services.voice.session import (
    BARGE_IN_RATIO,
    DEFAULT_MAX_SECONDS,
    DEFAULT_MAX_TURNS,
    ECHO_TAIL_SECONDS,
    ENDED_HANDED_OFF,
    ENDED_MAX_SECONDS,
    ENDED_MAX_TURNS,
    ENDED_SILENT,
    SILENCE_TIMEOUT_SECONDS,
    SessionState,
    begin_playback,
    end_playback,
    in_echo_window,
    is_speaking,
    record_refusal,
    should_accept_audio,
    should_barge_in,
    should_end,
)


def _state(**kw):
    base = dict(started_at=1000.0)
    base.update(kw)
    return SessionState(**base)


# ---- hearing ourselves ---------------------------------------------------


def test_the_agent_does_not_hear_itself_while_speaking():
    """The most likely embarrassing demo: the agent transcribes its own
    voice and replies to it."""
    state = _state()
    begin_playback(state, 1000.0, duration=3.0, level=1.0)

    # Our own audio coming back at playback level, mid-sentence.
    assert should_accept_audio(state, 1001.0, level=1.0) is False


def test_the_echo_tail_outlasts_the_playback():
    """The room keeps returning our audio after the speaker stops."""
    state = _state()
    begin_playback(state, 1000.0, duration=2.0, level=1.0)

    assert in_echo_window(state, 1002.2) is True   # just after playback
    assert in_echo_window(state, 1002.0 + ECHO_TAIL_SECONDS + 0.1) is False


def test_audio_after_the_tail_is_the_visitor():
    state = _state()
    begin_playback(state, 1000.0, duration=1.0, level=1.0)
    later = 1001.0 + ECHO_TAIL_SECONDS + 0.1

    assert should_accept_audio(state, later, level=0.2) is True


def test_a_session_that_never_spoke_hears_everything():
    assert should_accept_audio(_state(), 1000.0, level=0.1) is True
    assert in_echo_window(_state(), 1000.0) is False


# ---- barge-in ------------------------------------------------------------


def test_a_visitor_talking_over_the_agent_gets_through():
    """Echo returns attenuated, so a real interruption stands clear of
    it. A visitor should be able to cut in the way they would with a
    person."""
    state = _state()
    begin_playback(state, 1000.0, duration=5.0, level=1.0)

    loud = BARGE_IN_RATIO * 1.0 + 0.1
    assert should_accept_audio(state, 1001.0, level=loud) is True
    assert should_barge_in(state, 1001.0, level=loud) is True


def test_quiet_echo_is_not_mistaken_for_an_interruption():
    state = _state()
    begin_playback(state, 1000.0, duration=5.0, level=1.0)

    assert should_barge_in(state, 1001.0, level=1.0) is False


def test_barge_in_only_applies_while_actually_speaking():
    state = _state()
    begin_playback(state, 1000.0, duration=1.0, level=1.0)
    # Playback finished; loud audio is simply the next turn, not a
    # barge-in.
    assert should_barge_in(state, 1005.0, level=10.0) is False


def test_an_unknown_playback_level_keeps_the_ears_shut():
    """Without knowing how loud we are, echo and speech are
    indistinguishable. Staying deaf for a moment is recoverable; replying
    to ourselves is not."""
    state = _state()
    begin_playback(state, 1000.0, duration=3.0, level=0.0)

    assert should_accept_audio(state, 1001.0, level=5.0) is False


def test_ending_playback_early_still_leaves_the_tail():
    """A barge-in stops the speaker, but the room is still returning what
    already played."""
    state = _state()
    begin_playback(state, 1000.0, duration=10.0, level=1.0)
    end_playback(state, 1002.0)

    assert is_speaking(state, 1002.1) is False
    assert in_echo_window(state, 1002.1) is True


# ---- budgets -------------------------------------------------------------


def test_a_fresh_session_continues():
    assert should_end(_state(), 1001.0) is None


def test_the_turn_budget_is_a_hard_stop():
    assert should_end(_state(turns=DEFAULT_MAX_TURNS), 1001.0) == ENDED_MAX_TURNS


def test_the_time_budget_is_a_hard_stop():
    state = _state()
    assert should_end(state, 1000.0 + DEFAULT_MAX_SECONDS) == ENDED_MAX_SECONDS


def test_a_visitor_who_stops_talking_ends_the_session():
    state = _state(last_visitor_audio_at=1000.0)
    assert should_end(state, 1000.0 + SILENCE_TIMEOUT_SECONDS) == ENDED_SILENT


def test_silence_before_anyone_spoke_does_not_end_it():
    """Nothing to time out from yet."""
    assert should_end(_state(), 1005.0) is None


def test_a_handoff_outranks_every_budget():
    """Once a person is on the line the agent stops, regardless of how
    much time it had left."""
    state = _state(handed_off=True, turns=0)
    assert should_end(state, 1000.1) == ENDED_HANDED_OFF


def test_budgets_are_configurable_per_session():
    state = _state(turns=3)
    assert should_end(state, 1001.0, max_turns=3) == ENDED_MAX_TURNS
    assert should_end(state, 1001.0, max_turns=10) is None


# ---- refusals ------------------------------------------------------------


def test_refusals_are_kept_on_the_session():
    """The audit that matters most for a talking agent is not what it
    said but what it nearly said."""
    state = _state()
    record_refusal(state, "absence", "nobody is home", "Sorry, I can't help.")

    assert state.refusals == [{
        "reason": "absence",
        "matched": "nobody is home",
        "spoken_instead": "Sorry, I can't help.",
    }]


def test_elapsed_is_measured_from_the_start():
    assert _state().elapsed(1007.5) == 7.5
