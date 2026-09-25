from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from services.api.routes.cameras import _require_claimed_for_remote_camera_write


def _request(*, origin: str | None = None, client_host: str = "10.0.0.8") -> Request:
    headers = [] if origin is None else [(b"origin", origin.encode())]
    return Request({"type": "http", "headers": headers, "client": (client_host, 1234)})


def test_provisional_remote_camera_write_requires_claim():
    with pytest.raises(HTTPException) as error:
        _require_claimed_for_remote_camera_write(SimpleNamespace(is_provisional=True), _request())
    assert error.value.status_code == 403


def test_provisional_local_camera_write_remains_frictionless():
    _require_claimed_for_remote_camera_write(
        SimpleNamespace(is_provisional=True), _request(origin="http://localhost:4848")
    )


def test_claimed_user_can_write_from_remote_device():
    _require_claimed_for_remote_camera_write(SimpleNamespace(is_provisional=False), _request())
