"""Starter rules: the first-run path to a first alert.

These are data, not builders, so both clients offer the same four. A
starter that produced an unfireable rule would look like it worked and
never alert, which is worse than no starter at all.
"""
import pytest
from fastapi.testclient import TestClient

from services.api.main import app
from shared.auth import get_current_user, require_admin
from shared.rule_starters import STARTERS, starter_rule


def test_every_starter_has_a_complete_fireable_rule():
    for s in STARTERS:
        r = s["rule"]
        assert r["trigger_pattern"].get("type"), s["key"]
        assert r["actions"], s["key"]
        # notify works with nothing configured. A starter defaulting to
        # telegram or email would silently do nothing on a fresh install.
        assert all(a["type"] == "notify" for a in r["actions"]), s["key"]
        assert r["enabled"] is True, s["key"]


def test_starter_rule_scopes_to_one_camera_without_mutating_the_source():
    before = dict(STARTERS[0]["rule"]["trigger_pattern"])
    built = starter_rule(STARTERS[0]["key"], "cam-123")
    assert built["trigger_pattern"]["camera_id"] == "cam-123"
    assert STARTERS[0]["rule"]["trigger_pattern"] == before


def test_starter_rule_without_a_camera_watches_every_camera():
    built = starter_rule(STARTERS[0]["key"], None)
    assert "camera_id" not in built["trigger_pattern"]


def test_unknown_starter_is_none_not_a_half_built_rule():
    assert starter_rule("nope", "cam-1") is None


def test_keys_are_unique_and_titles_are_human():
    keys = [s["key"] for s in STARTERS]
    assert len(set(keys)) == len(keys)
    for s in STARTERS:
        assert s["title"][0].isupper() and s["blurb"]


def test_listing_endpoint_hides_the_rule_body():
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        r = TestClient(app).get("/api/rules/starters")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 200, r.text
    body = r.json()["starters"]
    assert len(body) == len(STARTERS)
    # The client picks a title, not a rule payload.
    assert all("rule" not in s for s in body)


def test_unknown_key_is_a_404():
    app.dependency_overrides[require_admin] = lambda: object()
    try:
        r = TestClient(app).post("/api/rules/starters", json={"key": "nope"})
    finally:
        app.dependency_overrides.pop(require_admin, None)
    assert r.status_code in (404, 422), r.text
