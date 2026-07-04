"""Tests for services.api.camera_probe — pure network probe helpers."""

import socket
import socketserver
import threading

import pytest

from services.api.camera_probe import (
    ERROR_HINTS,
    parse_target,
    probe_rtsp_describe,
    probe_tcp,
)


class _CannedRTSPHandler(socketserver.BaseRequestHandler):
    """Reads one request, replies with the server's canned status line."""

    def handle(self):
        self.request.recv(4096)
        self.request.sendall(self.server.canned_response.encode())


class _CannedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    canned_response = "RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n"


@pytest.fixture
def rtsp_server():
    """Yields a factory: pass a status line, get (host, port) of a live server."""
    servers = []

    def start(status_line: str):
        server = _CannedServer(("127.0.0.1", 0), _CannedRTSPHandler)
        server.canned_response = f"{status_line}\r\nCSeq: 1\r\n\r\n"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return server.server_address

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# parse_target
# ---------------------------------------------------------------------------


def test_parse_target_rtsp_default_port():
    assert parse_target("rtsp://cam.local/stream1") == ("cam.local", 554)


def test_parse_target_explicit_port():
    assert parse_target("rtsp://10.0.0.5:8554/live") == ("10.0.0.5", 8554)


def test_parse_target_http():
    assert parse_target("http://cam.local/snapshot.jpg") == ("cam.local", 80)


def test_parse_target_schemeless_defaults_to_rtsp():
    assert parse_target("10.0.0.5/stream") == ("10.0.0.5", 554)


# ---------------------------------------------------------------------------
# probe_tcp
# ---------------------------------------------------------------------------


def test_probe_tcp_ok(rtsp_server):
    host, port = rtsp_server("RTSP/1.0 200 OK")
    assert probe_tcp(host, port, timeout=2) == {"ok": True}


def test_probe_tcp_refused():
    result = probe_tcp("127.0.0.1", _free_port(), timeout=2)
    assert result["ok"] is False
    assert result["error_code"] == "refused"


def test_probe_tcp_dns():
    result = probe_tcp("no-such-host.nurby.invalid", 554, timeout=2)
    assert result["ok"] is False
    assert result["error_code"] == "dns"


def test_probe_tcp_empty_host():
    assert probe_tcp("", 554)["error_code"] == "dns"


# ---------------------------------------------------------------------------
# probe_rtsp_describe
# ---------------------------------------------------------------------------


def test_describe_ok(rtsp_server):
    host, port = rtsp_server("RTSP/1.0 200 OK")
    result = probe_rtsp_describe(f"rtsp://{host}:{port}/stream", timeout=2)
    assert result["ok"] is True


def test_describe_auth(rtsp_server):
    host, port = rtsp_server("RTSP/1.0 401 Unauthorized")
    result = probe_rtsp_describe(f"rtsp://{host}:{port}/stream", timeout=2)
    assert result["ok"] is False
    assert result["error_code"] == "auth"


def test_describe_not_found(rtsp_server):
    host, port = rtsp_server("RTSP/1.0 404 Stream Not Found")
    result = probe_rtsp_describe(f"rtsp://{host}:{port}/wrong", timeout=2)
    assert result["ok"] is False
    assert result["error_code"] == "not_found"


def test_describe_server_error(rtsp_server):
    host, port = rtsp_server("RTSP/1.0 503 Service Unavailable")
    result = probe_rtsp_describe(f"rtsp://{host}:{port}/stream", timeout=2)
    assert result["ok"] is False
    assert result["error_code"] == "http_error"


def test_describe_non_rtsp_response_falls_through(rtsp_server):
    # A non-RTSP server (e.g. an HTTP endpoint) should not hard-fail the
    # probe; the ffmpeg path decides.
    host, port = rtsp_server("HTTP/1.1 400 Bad Request")
    result = probe_rtsp_describe(f"rtsp://{host}:{port}/stream", timeout=2)
    assert result["ok"] is True


def test_describe_refused():
    port = _free_port()
    result = probe_rtsp_describe(f"rtsp://127.0.0.1:{port}/stream", timeout=2)
    assert result["error_code"] == "refused"


def test_describe_sends_basic_auth(rtsp_server):
    host, port = rtsp_server("RTSP/1.0 200 OK")
    result = probe_rtsp_describe(
        f"rtsp://{host}:{port}/stream", username="admin", password="secret", timeout=2
    )
    assert result["ok"] is True


def test_hints_cover_all_codes():
    for code in ("dns", "refused", "timeout", "auth", "not_found", "decode", "http_error"):
        assert code in ERROR_HINTS
