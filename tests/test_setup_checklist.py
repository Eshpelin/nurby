"""Tests for GET /api/system/setup-checklist."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api.routes.system import get_setup_checklist

DEMO_URL = "https://nurby.ai/demo/nurby-demo-loop.mp4"


def make_user():
    class U:
        role = "admin"

    return U()


def make_db(cameras, provider_count, rule_count, telegram_count, webhook_count):
    """AsyncMock db serving the checklist's queries in call order:
    cameras (execute), then scalars for provider/rule/telegram/webhook."""
    db = AsyncMock()
    cam_result = MagicMock()
    cam_result.all.return_value = cameras
    db.execute = AsyncMock(return_value=cam_result)
    db.scalar = AsyncMock(side_effect=[provider_count, rule_count, telegram_count, webhook_count])
    return db


def cam(stream_type, stream_url):
    row = MagicMock()
    row.stream_type = stream_type
    row.stream_url = stream_url
    return row


@pytest.mark.asyncio
async def test_fresh_install_all_unchecked():
    db = make_db([], 0, 0, 0, 0)
    with patch("shared.app_settings.get_setting", new=AsyncMock(return_value=False)), \
         patch("shared.email.resolve_smtp", new=AsyncMock(return_value={"host": None, "from_addr": None})):
        out = await get_setup_checklist(make_user(), db)
    assert out["camera_added"] == {"done": False, "demo_only": False}
    assert out["provider_connected"]["done"] is False
    assert out["first_rule_active"]["done"] is False
    assert out["notifications_configured"] == {"done": False, "channels": []}
    assert out["dismissed"] is False


@pytest.mark.asyncio
async def test_demo_only_camera_flagged():
    db = make_db([cam("file", DEMO_URL)], 1, 1, 1, 0)
    with patch("shared.app_settings.get_setting", new=AsyncMock(return_value=False)), \
         patch("shared.email.resolve_smtp", new=AsyncMock(return_value={"host": None, "from_addr": None})):
        out = await get_setup_checklist(make_user(), db)
    assert out["camera_added"] == {"done": True, "demo_only": True}
    assert out["notifications_configured"]["channels"] == ["telegram"]


@pytest.mark.asyncio
async def test_real_camera_and_smtp():
    db = make_db([cam("rtsp", "rtsp://10.0.0.5/stream")], 1, 1, 0, 2)
    with patch("shared.app_settings.get_setting", new=AsyncMock(return_value=True)), \
         patch(
             "shared.email.resolve_smtp",
             new=AsyncMock(return_value={"host": "smtp.example.com", "from_addr": "n@x.io"}),
         ):
        out = await get_setup_checklist(make_user(), db)
    assert out["camera_added"] == {"done": True, "demo_only": False}
    assert set(out["notifications_configured"]["channels"]) == {"smtp", "webhook_subscription"}
    assert out["dismissed"] is True
