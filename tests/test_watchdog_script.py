"""External watchdog poller logic (#211): deploy/watchdog/nurby_watchdog.py.

The script is stdlib-only and lives outside the package, so we load it by
path. We drive it with a fake ``urlopen`` and assert the poll classification
and the down/recovery alert transitions, without any real network or SMTP.
"""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "deploy" / "watchdog" / "nurby_watchdog.py"


def _load():
    spec = importlib.util.spec_from_file_location("nurby_watchdog", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wd = _load()


class _Resp:
    def __init__(self, status, body=b"{}"):
        self.status = status
        self._body = body

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_poll_200_is_healthy(monkeypatch):
    monkeypatch.setattr(wd.urllib.request, "urlopen", lambda *a, **k: _Resp(200, b'{"beacon":"alive"}'))
    healthy, detail = wd.poll("http://x/api/beacon", 5)
    assert healthy is True
    assert "200" in detail


def test_poll_503_is_unhealthy(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.HTTPError("http://x", 503, "degraded", {}, io.BytesIO(b'{"failing":["perception"]}'))

    monkeypatch.setattr(wd.urllib.request, "urlopen", _raise)
    healthy, detail = wd.poll("http://x/api/beacon", 5)
    assert healthy is False
    assert "503" in detail
    assert "perception" in detail


def test_poll_unreachable_is_unhealthy(monkeypatch):
    def _raise(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(wd.urllib.request, "urlopen", _raise)
    healthy, detail = wd.poll("http://x/api/beacon", 1)
    assert healthy is False
    assert "unreachable" in detail


def _main_with(monkeypatch, tmp_path, *, healthy, threshold=2):
    monkeypatch.setenv("NURBY_BEACON_URL", "http://x/api/beacon")
    monkeypatch.setenv("NURBY_FAIL_THRESHOLD", str(threshold))
    monkeypatch.setenv("NURBY_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(wd, "poll", lambda url, timeout: (healthy, "detail"))
    sent = []
    monkeypatch.setattr(wd, "dispatch_alert", lambda subject, body: sent.append(subject) or True)
    return sent


def test_alerts_only_after_threshold(monkeypatch, tmp_path):
    sent = _main_with(monkeypatch, tmp_path, healthy=False, threshold=2)
    assert wd.main() == 1  # first bad poll: below threshold, no alert
    assert sent == []
    assert wd.main() == 1  # second bad poll: threshold hit, alert once
    assert len(sent) == 1
    assert wd.main() == 1  # still down: no repeat spam
    assert len(sent) == 1


def test_recovery_sends_all_clear(monkeypatch, tmp_path):
    sent = _main_with(monkeypatch, tmp_path, healthy=False, threshold=1)
    assert wd.main() == 1
    assert len(sent) == 1  # down alert
    # Now healthy again.
    monkeypatch.setattr(wd, "poll", lambda url, timeout: (True, "HTTP 200"))
    assert wd.main() == 0
    assert len(sent) == 2  # all-clear
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["alerted"] is False and state["consecutive_failures"] == 0


def test_missing_url_exits_2(monkeypatch, tmp_path):
    monkeypatch.delenv("NURBY_BEACON_URL", raising=False)
    assert wd.main() == 2
