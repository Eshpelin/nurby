"""A failed migration must say why on stderr, whatever logging is doing.

Issue #180: the container restarted forever with nothing in the logs.
"""
from unittest import mock

import pytest


def test_migration_failure_reaches_stderr(capsys):
    from services.api import main

    with mock.patch("alembic.command.upgrade", side_effect=RuntimeError("Can't locate revision 'deadbeef'")):
        with pytest.raises(RuntimeError):
            main._run_migrations()

    err = capsys.readouterr().err
    assert "FATAL: database migration failed" in err
    assert "deadbeef" in err
    # The traceback, not just the one-liner: the operator needs to know
    # which revision file and which line.
    assert "Traceback" in err


def test_application_logger_has_a_handler():
    # Importing the app must leave the root logger with somewhere to
    # send records. Without this, every logger.* call in the API was
    # silently dropped under uvicorn.
    import logging

    import services.api.main  # noqa: F401

    assert logging.getLogger().handlers, "root logger has no handler"
