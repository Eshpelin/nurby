"""One source of truth for guardian words and defaults.

Both clients used to hardcode the alert kinds, their defaults and the
delivery channels. A ninth alert kind added to entitlements.py would not
have appeared in either.
"""
from fastapi.testclient import TestClient

from services.api.main import app
from services.guardian.entitlements import (
    DEFAULT_ALERT_PREFS,
    DEFAULT_NOTIFY_CHANNELS,
    NOTIFY_CHANNELS,
)
from shared.auth import get_current_user


def _vocab() -> dict:
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        r = TestClient(app).get("/api/guardian/vocabulary")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_alert_kind_is_served_with_its_real_default():
    served = {a["key"]: a["default"] for a in _vocab()["alert_kinds"]}
    assert served == DEFAULT_ALERT_PREFS


def test_every_alert_kind_has_a_human_label():
    for a in _vocab()["alert_kinds"]:
        assert a["label"] and a["label"] != a["key"], a["key"]


def test_channels_match_entitlements_exactly():
    served = _vocab()["notify_channels"]
    assert [c["key"] for c in served] == list(NOTIFY_CHANNELS)
    assert {c["key"]: c["default"] for c in served} == DEFAULT_NOTIFY_CHANNELS


def test_tiers_cover_the_three_the_backend_accepts():
    from services.guardian.entitlements import _TIERS

    assert {t["key"] for t in _vocab()["tiers"]} == set(_TIERS)
    for t in _vocab()["tiers"]:
        assert t["label"] and t["hint"]
