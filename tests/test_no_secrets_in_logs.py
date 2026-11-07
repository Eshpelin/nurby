"""Secrets must never reach the logs (#329).

Two paths: the one-time setup code issued by first-run bootstrap
(caplog on the handler, direct-invocation unit style per suite
convention), and the per-session JWT secret generated at config import
(a fresh interpreter is the only faithful way to observe that warning).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

from starlette.requests import Request

from services.api.routes import auth as auth_routes


def _req() -> Request:
    return Request({
        "type": "http", "headers": [], "scheme": "http",
        "server": ("localhost", 4848), "client": ("127.0.0.1", 5150),
    })


def _fresh_install_db():
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []  # no users yet
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()

    async def _refresh(obj, **_kw):
        # The real session assigns the PK on flush; the stub must too, or
        # UserResponse validation fails exactly like a real unflushed row.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def test_bootstrap_logs_marker_but_never_the_setup_code(caplog):
    with caplog.at_level(logging.WARNING, logger="nurby.api.auth"):
        resp = asyncio.run(
            auth_routes.bootstrap(request=_req(), response=None, db=_fresh_install_db())
        )
    assert resp.setup_code, "a setup code was issued — prove it COULD have leaked"
    messages = [r.getMessage() for r in caplog.records]
    assert any("setup code" in m.lower() for m in messages), "provisioning marker expected"
    assert not any(resp.setup_code in m for m in messages), "the code value must never be logged"


def test_generated_jwt_secret_warning_does_not_print_the_secret():
    # The warning fires at import time with the default secret in place;
    # a subprocess observes it faithfully without poisoning this
    # process's shared settings object.
    proc = subprocess.run(
        [sys.executable, "-c", "import shared.config"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "insecure default" in proc.stderr, "the warning should still fire"
    assert "JWT_SECRET=" not in proc.stderr, "the secret value must never be printed"
