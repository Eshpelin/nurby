"""Matching a subject against a signature or subject key.

Keys written after #145 are per-subject: one name, one cluster id. Keys
written before it can be joined, ``"Ahmed,Sara"``. Both must be findable
by exact subject, and neither must match a substring: a person named Sam
must not match Samantha's incidents (#151).

``subject_key_has`` compiles to ``value = ANY(string_to_array(key, ','))``,
which is exact on each comma-separated element. It replaces the
``ILIKE '%name%'`` fallback that had the substring problem.
"""

from __future__ import annotations

from sqlalchemy import String, any_, func
from sqlalchemy.sql import ColumnElement


def subject_key_has(column: ColumnElement, value: str) -> ColumnElement:
    """SQL predicate: ``value`` is one of the comma-separated elements of
    ``column``. Exact, case-sensitive, and correct for both per-subject
    and legacy joined keys."""
    return value == any_(func.string_to_array(column, ",", type_=String))


def key_elements(key: str | None) -> list[str]:
    """The subjects a stored key names. Pure.

    ``"Ahmed,Sara"`` -> ``["Ahmed", "Sara"]``; ``"Ahmed"`` -> ``["Ahmed"]``;
    empty or None -> ``[]``. Whitespace around commas is stripped because
    some legacy rows carry it.
    """
    if not key:
        return []
    return [part.strip() for part in key.split(",") if part.strip()]


def key_names(key: str | None, name: str) -> bool:
    """Python twin of ``subject_key_has``, for rows already loaded. Pure."""
    return name in key_elements(key)
