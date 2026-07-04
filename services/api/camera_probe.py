"""Lightweight network pre-probes for camera stream URLs.

These run before the heavyweight OpenCV/ffmpeg open so that connection
failures can be classified (dns / refused / timeout / auth / not_found)
instead of collapsing into one generic "failed to open stream" message.
All functions are synchronous; callers run them in a thread pool.
"""

from __future__ import annotations

import base64
import socket
from urllib.parse import urlparse

DEFAULT_PORTS = {"rtsp": 554, "rtsps": 322, "http": 80, "https": 443}

# Shared human hints keyed by error_code. Reused by the doctor checks.
ERROR_HINTS: dict[str, str] = {
    "dns": (
        "The hostname could not be resolved. Check the address for typos "
        "and make sure the camera is on the same network."
    ),
    "refused": (
        "The device is reachable but nothing is listening on that port. "
        "Check the port number and that RTSP/HTTP is enabled on the camera."
    ),
    "timeout": (
        "No response from the camera. Check that it is powered on, on the "
        "same network, and that no firewall blocks the port."
    ),
    "auth": (
        "The camera rejected the credentials. Check the username and "
        "password. Many cameras use 'admin' plus the password printed on "
        "the device sticker."
    ),
    "not_found": (
        "The camera answered, but the stream path was not found. Check the "
        "path part of the URL against the guide for your camera brand."
    ),
    "decode": (
        "The camera answered, but the video stream could not be decoded. "
        "Check the stream path and the camera's codec settings (H.264 "
        "works best)."
    ),
    "http_error": "The camera returned an unexpected response. Check the URL.",
}


def parse_target(url: str) -> tuple[str, int]:
    """Extract (host, port) from a stream URL, applying scheme defaults."""
    parsed = urlparse(url if "://" in url else f"rtsp://{url}")
    host = parsed.hostname or ""
    port = parsed.port or DEFAULT_PORTS.get(parsed.scheme or "rtsp", 554)
    return host, port


def probe_tcp(host: str, port: int, timeout: float = 4.0) -> dict:
    """Try a bare TCP connect. Classifies dns / refused / timeout failures."""
    if not host:
        return {"ok": False, "error_code": "dns", "detail": "No hostname in URL"}
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True}
    except socket.gaierror:
        return {"ok": False, "error_code": "dns", "detail": f"Could not resolve {host}"}
    except ConnectionRefusedError:
        return {
            "ok": False,
            "error_code": "refused",
            "detail": f"Connection refused on {host}:{port}",
        }
    except (socket.timeout, TimeoutError):
        return {
            "ok": False,
            "error_code": "timeout",
            "detail": f"No response from {host}:{port}",
        }
    except OSError as exc:
        return {"ok": False, "error_code": "unknown", "detail": str(exc)}


def probe_rtsp_describe(
    url: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> dict:
    """Send an RTSP DESCRIBE and classify the status line.

    Returns ok=True on 2xx. 401/407 map to "auth" (note: only Basic auth is
    attempted here; a Digest-only camera returns 401 even with valid
    credentials, so callers should fall through to the full ffmpeg open when
    credentials were provided). 404 maps to "not_found".
    """
    host, port = parse_target(url)
    if not host:
        return {"ok": False, "error_code": "dns", "detail": "No hostname in URL"}
    request = (
        f"DESCRIBE {url} RTSP/1.0\r\n"
        "CSeq: 1\r\n"
        "Accept: application/sdp\r\n"
        "User-Agent: nurby-probe\r\n"
    )
    if username:
        token = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
        request += f"Authorization: Basic {token}\r\n"
    request += "\r\n"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request.encode())
            raw = sock.recv(4096).decode(errors="replace")
    except socket.gaierror:
        return {"ok": False, "error_code": "dns", "detail": f"Could not resolve {host}"}
    except ConnectionRefusedError:
        return {
            "ok": False,
            "error_code": "refused",
            "detail": f"Connection refused on {host}:{port}",
        }
    except (socket.timeout, TimeoutError):
        return {
            "ok": False,
            "error_code": "timeout",
            "detail": f"No response from {host}:{port}",
        }
    except OSError as exc:
        return {"ok": False, "error_code": "unknown", "detail": str(exc)}

    status_line = raw.split("\r\n", 1)[0]
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("RTSP/"):
        # Not an RTSP server (or garbage); let the ffmpeg path decide.
        return {"ok": True, "detail": f"Non-RTSP response: {status_line[:80]}"}
    try:
        status = int(parts[1])
    except ValueError:
        return {"ok": True, "detail": f"Unparseable status: {status_line[:80]}"}

    if 200 <= status < 300:
        return {"ok": True}
    if status in (401, 407):
        return {
            "ok": False,
            "error_code": "auth",
            "detail": f"Camera returned {status} for DESCRIBE",
        }
    if status == 404:
        return {
            "ok": False,
            "error_code": "not_found",
            "detail": f"Stream path not found ({status})",
        }
    return {
        "ok": False,
        "error_code": "http_error",
        "detail": f"Camera returned RTSP status {status}",
    }
