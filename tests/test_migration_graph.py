"""Alembic migration graph integrity.

Parallel work streams keep landing migrations on main; a duplicated
revision id or a dangling down_revision silently breaks
``alembic upgrade head`` — which the API runs at startup and treats as
fatal. These tests fail in CI instead (see the b3c4d5e6f7a8 collision
between the notifications table and the storage-profiles migrations).
"""

import ast
import os
import re

import pytest

VERSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions")


def _graph():
    """{revision: (filename, down_revisions)} for every migration file."""
    revs: dict[str, tuple[str, list[str]]] = {}
    for f in os.listdir(VERSIONS_DIR):
        if not f.endswith(".py"):
            continue
        s = open(os.path.join(VERSIONS_DIR, f)).read()
        m = re.search(r"^revision(?::[^=]*)?\s*=\s*(.+)$", s, re.M)
        if not m:
            continue
        try:
            rev = ast.literal_eval(m.group(1).strip())
        except Exception:
            rev = m.group(1).strip().strip("\"'")
        d = re.search(r"^down_revision(?::[^=]*)?\s*=\s*(.+)$", s, re.M)
        downs: list[str] = []
        if d:
            try:
                down = ast.literal_eval(d.group(1).strip())
            except Exception:
                down = d.group(1).strip().strip("\"'")
            if isinstance(down, tuple):
                downs = [x for x in down if isinstance(x, str)]
            elif isinstance(down, str):
                downs = [down]
        revs[rev] = (f, downs)
    return revs


def test_no_duplicate_revision_ids():
    """The parse itself fails on duplicates: build the map from raw ids to
    catch two files claiming the same revision."""
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for f in os.listdir(VERSIONS_DIR):
        if not f.endswith(".py"):
            continue
        s = open(os.path.join(VERSIONS_DIR, f)).read()
        m = re.search(r"^revision(?::[^=]*)?\s*=\s*(.+)$", s, re.M)
        if not m:
            continue
        try:
            rev = ast.literal_eval(m.group(1).strip())
        except Exception:
            rev = m.group(1).strip().strip("\"'")
        if rev in seen:
            dupes.append(f"{rev}: {seen[rev]} vs {f}")
        seen[rev] = f
    assert not dupes, f"duplicate revision ids: {dupes}"


def test_single_head_and_no_dangling_parents():
    revs = _graph()
    assert revs, "no migrations found"
    referenced = {d for (_, downs) in revs.values() for d in downs}
    dangling = referenced - set(revs)
    assert not dangling, f"dangling down_revisions (parent never lands): {sorted(dangling)}"
    heads = [r for r in revs if r not in referenced]
    assert len(heads) == 1, (
        "alembic upgrade head requires exactly one head; "
        f"found {len(heads)}: {sorted((h, revs[h][0]) for h in heads)}. "
        "Rebase your migration onto the current head."
    )


def test_revision_id_matches_filename():
    """A filename/revision mismatch makes migrations unfindable by id in
    some tooling; keep them aligned."""
    for f in os.listdir(VERSIONS_DIR):
        if not f.endswith(".py"):
            continue
        s = open(os.path.join(VERSIONS_DIR, f)).read()
        m = re.search(r"^revision(?::[^=]*)?\s*=\s*(.+)$", s, re.M)
        if m:
            try:
                rev = ast.literal_eval(m.group(1).strip())
            except Exception:
                rev = m.group(1).strip().strip("\"'")
            assert f.startswith(str(rev)), f"{f} does not start with its revision id {rev}"
