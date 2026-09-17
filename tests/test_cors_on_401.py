"""A 401 from an authenticated endpoint must still carry CORS headers.

Regression test for issue #188. Starlette's CORSMiddleware always emits
``access-control-allow-credentials`` but only emits
``access-control-allow-origin`` for an origin in the allow list. When the web
dashboard origin was missing from that list, an expired-token 401 arrived with
credentials-but-no-origin, which the browser reports as a CORS failure instead
of a plain sign-in problem.
"""

from fastapi.testclient import TestClient

from services.api.main import app, _CORS_ORIGINS

DASHBOARD_ORIGIN = "http://localhost:3210"


def test_dashboard_origin_is_allowed():
    assert DASHBOARD_ORIGIN in _CORS_ORIGINS


def test_401_from_authenticated_endpoint_carries_allow_origin():
    client = TestClient(app)
    resp = client.get(
        "/api/voice/sessions?active=true&limit=1",
        headers={"Origin": DASHBOARD_ORIGIN, "Authorization": "Bearer not-a-real-token"},
    )
    # An expired / invalid token yields 401, not a CORS-shaped error.
    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") == DASHBOARD_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_missing_token_still_carries_allow_origin():
    client = TestClient(app)
    resp = client.get(
        "/api/voice/sessions?active=true&limit=1",
        headers={"Origin": DASHBOARD_ORIGIN},
    )
    # HTTPBearer rejects the request (401/403) but the response is still a
    # well-formed CORS response the browser will accept.
    assert resp.status_code in (401, 403)
    assert resp.headers.get("access-control-allow-origin") == DASHBOARD_ORIGIN
