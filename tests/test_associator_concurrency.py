"""Concurrency regression tests for the learned-association ledger (#260)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from services.perception.associator import record_pairing


class _Result:
    def __init__(self, row=None):
        self.row = row

    def scalars(self):
        return self

    def first(self):
        return self.row

    def scalar_one_or_none(self):
        return self.row


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FirstCreateRaceDb:
    """The second worker sees no row, then loses the unique-key race."""

    def __init__(self, existing):
        self.existing = existing
        self.calls = 0
        self.added = []

    async def execute(self, statement):
        self.calls += 1
        # Initial edge lookup and initial episode lookup both miss. The
        # recovery lookup finds the row committed by the winning worker, and
        # the final ledger lookup proves this episode was already folded.
        if self.calls in (3, 4):
            return _Result(self.existing)
        return _Result(None)

    def begin_nested(self):
        return _Savepoint()

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        if len(self.added) == 1:
            raise IntegrityError("duplicate association", None, Exception())


@pytest.mark.asyncio
async def test_first_create_race_reuses_existing_episode_without_aborting_transaction():
    existing = SimpleNamespace(id="edge-1")
    db = _FirstCreateRaceDb(existing)

    result = await record_pairing(
        db,
        subject_kind="person",
        subject_key="person-1",
        object_kind="vehicle",
        object_key="vehicle-1",
        object_label="Car",
        relation="uses",
        when=datetime(2026, 9, 27, 10, tzinfo=timezone.utc),
        tz_name="UTC",
        min_days=3,
        episode_key="journey-1",
    )

    assert result is existing
    assert db.calls == 4
    # The losing worker's transient candidate stayed inside the savepoint;
    # it did not leak a second row into the caller's transaction.
    assert len(db.added) == 1
