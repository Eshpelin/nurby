"""Dashboard widget proxy: egress policy, secret injection, caps, cache.

Exercises services/api/widget_proxy.py directly (no DB), which is where the
security-sensitive behaviour lives: the auth secret must reach the upstream
but never the returned payload, cloud metadata must be refused, and
oversized/binary/redirect responses must be rejected.
"""

import asyncio

import services.api.widget_proxy as wp


class FakeResp:
    def __init__(self, status=200, content=b"{}", headers=None, is_redirect=False):
        self.status_code = status
        self.content = content
        self.headers = headers or {"content-type": "application/json"}
        self.is_redirect = is_redirect


class FakeClient:
    def __init__(self, resp, capture):
        self._resp = resp
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, params=None, content=None):
        self._capture.update(method=method, url=url, headers=dict(headers or {}),
                             params=dict(params or {}), content=content)
        return self._resp


def _patch(monkeypatch, resp):
    """Bypass the (real) egress check and stub httpx with a recording client."""
    capture: dict = {}
    monkeypatch.setattr(wp, "webhook_target_rejection", lambda url: _none())
    monkeypatch.setattr(wp.httpx, "AsyncClient", lambda **kw: FakeClient(resp, capture))
    return capture


async def _none():
    return None


def _run(source, secret):
    return asyncio.run(wp.fetch_widget_data(source, secret))


# ── egress policy (real guard) ──

def test_blocks_cloud_metadata():
    res = _run({"url": "http://169.254.169.254/latest/meta-data/"}, None)
    assert res["ok"] is False
    assert "blocked" in res["error"]


def test_rejects_non_http_scheme():
    res = _run({"url": "ftp://example.com/data"}, None)
    assert res["ok"] is False
    assert "http" in res["error"]


def test_empty_url():
    assert _run({"url": ""}, None)["ok"] is False


# ── secret injection (never echoed) ──

def test_bearer_injected_and_secret_not_echoed(monkeypatch):
    cap = _patch(monkeypatch, FakeResp(content=b'{"temp": 21}'))
    res = _run({"url": "http://sensor.local/api", "auth_kind": "bearer"}, "topsecret")
    assert cap["headers"]["Authorization"] == "Bearer topsecret"
    assert "topsecret" not in str(res)  # secret never travels back to the browser
    assert res["ok"] is True
    assert res["data"] == {"temp": 21}


def test_header_auth_injected(monkeypatch):
    cap = _patch(monkeypatch, FakeResp())
    _run({"url": "http://x.local", "auth_kind": "header", "auth_name": "X-Key"}, "k123")
    assert cap["headers"]["X-Key"] == "k123"


def test_query_auth_injected(monkeypatch):
    cap = _patch(monkeypatch, FakeResp())
    _run({"url": "http://x.local", "auth_kind": "query", "auth_name": "apikey"}, "q123")
    assert cap["params"]["apikey"] == "q123"


def test_no_auth_when_kind_none(monkeypatch):
    cap = _patch(monkeypatch, FakeResp())
    _run({"url": "http://x.local", "auth_kind": "none"}, "ignored")
    assert "Authorization" not in cap["headers"]


# ── response caps ──

def test_rejects_oversized_response(monkeypatch):
    _patch(monkeypatch, FakeResp(content=b"x" * (256 * 1024 + 1)))
    res = _run({"url": "http://x.local"}, None)
    assert res["ok"] is False
    assert "too large" in res["error"]


def test_rejects_binary_content_type(monkeypatch):
    _patch(monkeypatch, FakeResp(content=b"\x89PNG", headers={"content-type": "image/png"}))
    res = _run({"url": "http://x.local"}, None)
    assert res["ok"] is False
    assert "content-type" in res["error"]


def test_redirect_not_followed(monkeypatch):
    _patch(monkeypatch, FakeResp(status=302, is_redirect=True))
    res = _run({"url": "http://x.local"}, None)
    assert res["ok"] is False
    assert "redirect" in res["error"]


def test_text_content_passed_through(monkeypatch):
    _patch(monkeypatch, FakeResp(content=b"hello", headers={"content-type": "text/plain"}))
    res = _run({"url": "http://x.local"}, None)
    assert res["ok"] is True
    assert res["data"] == "hello"


# ── cache ──

def test_cache_hit_and_expiry():
    wp.cache_clear("w1")
    wp.cache_put("w1", {"ok": True, "data": 1}, ttl=100)
    assert wp.cache_get("w1") == {"ok": True, "data": 1}
    wp.cache_put("w1", {"ok": True, "data": 2}, ttl=0)  # already expired
    assert wp.cache_get("w1") is None


def test_cache_clear():
    wp.cache_put("w2", {"ok": True}, ttl=100)
    wp.cache_clear("w2")
    assert wp.cache_get("w2") is None
