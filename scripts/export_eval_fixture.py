#!/usr/bin/env python3
"""Export a real agent run as an eval fixture (issue #140).

    python scripts/export_eval_fixture.py <run_id>
    python scripts/export_eval_fixture.py --failures        # list candidates
    python scripts/export_eval_fixture.py --failures --export-all

Fixtures land in ``tests/agent_fixtures/`` unless ``--out`` says
otherwise. The generated ``expected`` block records what the run DID; a
human edits it into what it SHOULD do before the fixture means anything.
That is deliberate, and the file says so at the top.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.agent.eval.export import (  # noqa: E402
    FAILURE_STATUSES,
    build_fixture,
)
from shared.database import async_session  # noqa: E402
from shared.models import AgentRun, AgentToolCall  # noqa: E402

DEFAULT_OUT = Path("tests/agent_fixtures")


async def _load(run_id: uuid.UUID):
    async with async_session() as db:
        run = await db.get(AgentRun, run_id)
        if run is None:
            return None, []
        calls = (
            await db.execute(
                select(AgentToolCall)
                .where(AgentToolCall.run_id == run_id)
                .order_by(AgentToolCall.turn_index, AgentToolCall.created_at)
            )
        ).scalars().all()
        return run, list(calls)


async def _failures(limit: int):
    async with async_session() as db:
        return list((
            await db.execute(
                select(AgentRun)
                .where(AgentRun.status.in_(FAILURE_STATUSES))
                .order_by(AgentRun.started_at.desc())
                .limit(limit)
            )
        ).scalars().all())


def _write(fixture: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{fixture['id']}.yaml"
    path.write_text(
        yaml.safe_dump(fixture, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return path


async def _export_one(run_id: uuid.UUID, out_dir: Path) -> int:
    run, calls = await _load(run_id)
    if run is None:
        print(f"no run {run_id}", file=sys.stderr)
        return 1
    path = _write(build_fixture(run, calls), out_dir)
    print(f"wrote {path} ({len(calls)} tool calls)")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", nargs="?", help="agent run id to export")
    parser.add_argument("--failures", action="store_true",
                        help="list recent runs that ended badly")
    parser.add_argument("--export-all", action="store_true",
                        help="with --failures, export every one listed")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.failures:
        runs = await _failures(args.limit)
        if not runs:
            print("no failed runs recorded")
            return 0
        for run in runs:
            print(f"{run.id}  {run.status:<18} {(run.question or '')[:60]}")
        if args.export_all:
            for run in runs:
                await _export_one(run.id, args.out)
        else:
            print("\nre-run with --export-all to write fixtures for these")
        return 0

    if not args.run_id:
        parser.error("give a run id, or --failures")
    return await _export_one(uuid.UUID(args.run_id), args.out)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
