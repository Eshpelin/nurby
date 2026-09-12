"""What the agent is allowed to say to a stranger (issue #157).

Once a camera can hold a conversation, the dangerous failure stops being
"it said something odd" and becomes "it told someone useful something
about this household". The delivery example from #152 is exactly where
it bites:

    "Is this the house of Ahmed Saqib?"

Confirming that hands an unverified stranger the resident's name, and the
obvious follow-up ("is Ahmed home?") tells them the house is empty.

This module is the last check before anything is spoken. It runs on the
*rendered* line, not the prompt, because a prompt that looks safe can
produce an unsafe sentence, and because the model is not the only thing
that can put words here.

**It is a backstop, not the defence.** A pattern matcher cannot enumerate
every way to say "nobody is home", and treating it as a guarantee would
be the mistake. The real protections are structural and live elsewhere:
the conversation agent gets no tools, no household context, and a fixed
prompt. This catches the residue.

Refusals are conservative on purpose. A visitor hearing "I can't help
with that" is a mildly unhelpful doorbell; a visitor hearing "they're
away until Tuesday" is a burglary.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("nurby.voice.disclosure")

# Longest line we will speak in a conversation turn. A doorstep reply is
# a sentence or two; anything longer is the model rambling at a stranger.
MAX_REPLY_CHARS = 240

# What a refused line is replaced with. Deliberately bland and final: it
# gives nothing away, and it does not invite the visitor to rephrase.
SAFE_FALLBACK = "Sorry, I can't help with that. I've let the household know you're here."


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str | None = None
    matched: str | None = None
    replacement: str | None = None

    @classmethod
    def ok(cls) -> "Verdict":
        return cls(True)

    @classmethod
    def refuse(cls, reason: str, matched: str | None = None) -> "Verdict":
        return cls(False, reason, matched, SAFE_FALLBACK)


# Absence. The single worst thing this feature can say, and a naive
# assistant says it readily and helpfully.
_ABSENCE = re.compile(
    r"\b("
    r"nobody(?:'s| is)? (?:home|here|in)"
    r"|no[ -]?one(?:'s| is)? (?:home|here|in)"
    r"|there'?s no one"
    r"|the house is empty"
    r"|(?:they|he|she|we)(?:'re| are|'s| is) (?:not|n't) (?:home|here|in)"
    r"|(?:they|he|she|we) (?:are|is)n'?t (?:home|here)"
    r"|(?:they|he|she)(?:'re| are|'s| is) (?:out|away|on holiday|on vacation)"
    r"|(?:i'?m|i am) (?:home )?alone"
    r"|home alone"
    r"|empty (?:house|home)"
    r")\b",
    re.IGNORECASE,
)

# When someone will be back, or when the house is unoccupied. Same class
# of harm as absence, one step removed.
_SCHEDULE = re.compile(
    r"\b("
    r"(?:back|home|returns?|returning) (?:on|at|around|by|after|in) \S+"
    r"|(?:will|should) be (?:back|home)"
    r"|(?:leaves?|left) (?:at|for|around)"
    r"|(?:until|till) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next)"
    r"|gets? (?:home|back) at"
    r")\b",
    re.IGNORECASE,
)

# Anything that helps someone get in. A conversational agent has no
# business discussing access under any configuration.
_ACCESS = re.compile(
    r"\b("
    r"(?:door|gate|garage) is (?:un)?locked"
    r"|the (?:code|combination|pin|password) is"
    r"|key is (?:under|in|behind|hidden)"
    r"|spare key"
    r"|you can (?:come|go) (?:in|inside)"
    r"|let yourself in"
    r"|i(?:'ll| will|'m going to| am going to)? ?(?:open|unlock)(?:ing)? the"
    r"|leave it (?:inside|in the house)"
    r")\b",
    re.IGNORECASE,
)

# Claims to be a person, or to be able to act physically. The agent must
# never imply someone is present.
_IMPERSONATION = re.compile(
    r"\b("
    r"i'?m (?:the )?(?:owner|homeowner|resident|husband|wife|father|mother|dad|mum|mom)"
    r"|i live here"
    r"|i'?ll (?:come|be) (?:down|out|right there)"
    r"|(?:i'?m|i am) (?:coming|on my way)"
    r"|hold on,? i'?ll get"
    r")\b",
    re.IGNORECASE,
)

_RULES = (
    ("absence", _ABSENCE),
    ("schedule", _SCHEDULE),
    ("access", _ACCESS),
    ("impersonation", _IMPERSONATION),
)


def _normalise(text: str) -> str:
    """Fold the cheap evasions a model produces by accident. Pure.

    Not an attempt to defeat a determined adversary: the model is not
    adversarial here, it is careless. Collapsing whitespace and unifying
    apostrophes catches "nobody  is   home" and the curly-quote variant
    without pretending to do more.
    """
    folded = (text or "").replace("’", "'").replace("ʼ", "'")
    return re.sub(r"\s+", " ", folded).strip()


def contains_household_name(text: str, names: list[str] | None) -> str | None:
    """The first household name the line would say out loud. Pure.

    Greeting a recognised person by name where a stranger can hear tells
    them both who lives here and who is currently home, so this applies
    even when the agent is right about who it is talking to.
    """
    haystack = _normalise(text).lower()
    for name in names or []:
        cleaned = (name or "").strip()
        # One-character or empty names would match everything.
        if len(cleaned) < 2:
            continue
        if re.search(rf"\b{re.escape(cleaned.lower())}\b", haystack):
            return cleaned
    return None


def check_reply(
    text: str,
    *,
    household_names: list[str] | None = None,
    never_say: list[str] | None = None,
    may_confirm: list[str] | None = None,
) -> Verdict:
    """Whether this line may be spoken to a visitor. Pure, for tests.

    ``may_confirm`` is an allowlist of disclosure keys a household has
    explicitly turned on. It is deliberately narrow and cannot unlock the
    absence, access or impersonation rules: those are refused under every
    configuration, because no household setting should be able to make
    "nobody is home" sayable.
    """
    line = _normalise(text)
    if not line:
        return Verdict.refuse("empty")
    if len(line) > MAX_REPLY_CHARS:
        return Verdict.refuse("too_long", f"{len(line)} chars")

    allowed_keys = {k.strip().lower() for k in (may_confirm or [])}

    for reason, pattern in _RULES:
        match = pattern.search(line)
        if not match:
            continue
        # Only `schedule` is ever unlockable, and only by an explicit
        # opt-in. Absence, access and impersonation are absolute.
        if reason == "schedule" and "schedule" in allowed_keys:
            continue
        return Verdict.refuse(reason, match.group(0))

    name = contains_household_name(line, household_names)
    if name and "names" not in allowed_keys:
        return Verdict.refuse("identity", name)

    for phrase in never_say or []:
        cleaned = (phrase or "").strip()
        if cleaned and cleaned.lower() in line.lower():
            return Verdict.refuse("never_say", cleaned)

    return Verdict.ok()


def safe_reply(
    text: str,
    *,
    household_names: list[str] | None = None,
    never_say: list[str] | None = None,
    may_confirm: list[str] | None = None,
) -> tuple[str, Verdict]:
    """The line to actually speak, and why it changed. Pure.

    Returns the fallback rather than nothing when a line is refused: a
    visitor left in silence rings again, or assumes the house is empty,
    which is the outcome the refusal was protecting against.
    """
    verdict = check_reply(
        text,
        household_names=household_names,
        never_say=never_say,
        may_confirm=may_confirm,
    )
    if verdict.allowed:
        return _normalise(text), verdict
    logger.info(
        "refused a conversation reply: %s (%r)", verdict.reason, verdict.matched
    )
    return SAFE_FALLBACK, verdict
