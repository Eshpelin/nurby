"""Scoring metrics for the golden harness.

Deliberately simple and transparent. Every metric is a pure function
over normalized text so a scorecard number is reproducible and a
reviewer can hand-check it. Three levels of strictness, matching the
issue's "exact / keyword / semantic-lite" guidance.

- ``exact_match``. Normalized string equality. Used only where a closed
  answer exists.
- ``keyword_coverage``. Fraction of required phrases present. The
  primary deterministic gate for closed vocabularies (object class,
  known person, event presence wording).
- ``semantic_lite``. Token-set Jaccard overlap against a reference. A
  cheap stand-in for the LLM-as-judge score a live run would add; it is
  reported, never a hard gate, because it is easy to game.

No metric here needs a model, a network call, or a random seed.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase and collapse to single-spaced alphanumerics."""
    return " ".join(_WORD_RE.findall((text or "").lower()))


def tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def exact_match(prediction: str, reference: str) -> bool:
    return normalize(prediction) == normalize(reference)


def phrase_present(text: str, phrase: str) -> bool:
    """Whether ``phrase`` appears as a normalized substring of ``text``.

    Phrases may be multi-word ("mail carrier"); normalization on both
    sides makes the match punctuation- and case-insensitive.
    """
    norm_text = normalize(text)
    norm_phrase = normalize(phrase)
    if not norm_phrase:
        return True
    return norm_phrase in norm_text


def keyword_coverage(text: str, keywords: list[str]) -> float:
    """Fraction of ``keywords`` present in ``text`` (1.0 if none asked)."""
    if not keywords:
        return 1.0
    hits = sum(1 for kw in keywords if phrase_present(text, kw))
    return hits / len(keywords)


def forbidden_violations(text: str, forbidden: list[str]) -> list[str]:
    """Return the forbidden phrases that leaked into ``text``."""
    return [kw for kw in (forbidden or []) if phrase_present(text, kw)]


def semantic_lite(prediction: str, reference: str) -> float:
    """Token-set Jaccard overlap in ``[0, 1]`` (1.0 if no reference)."""
    ref = tokens(reference)
    if not ref:
        return 1.0
    pred = tokens(prediction)
    if not pred:
        return 0.0
    inter = pred & ref
    union = pred | ref
    return len(inter) / len(union)


__all__ = [
    "exact_match",
    "forbidden_violations",
    "keyword_coverage",
    "normalize",
    "phrase_present",
    "semantic_lite",
    "tokens",
]
