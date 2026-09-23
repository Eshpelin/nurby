#!/usr/bin/env python3
"""External dead-man's switch for Nurby (#211).

Run this OFF the Nurby host: on a hosted cron (GitHub Actions, a cloud
function, a VPS), a second machine, or a Raspberry Pi on a different power
strip and network. Its whole job is to notice when Nurby goes silent and
tell you through a channel that does NOT depend on the Nurby box, because
the box is exactly what may be down.

It polls Nurby's beacon (``GET /api/beacon``, see
docs/operations/dead-mans-switch.md). The beacon returns:

* HTTP 200 - end-to-end monitoring confirmed (DB + ingestion + perception
  + a producing pipeline).
* HTTP 503 - Nurby answered but monitoring is degraded (e.g. perception
  died while the API stayed up). The JSON body lists what is failing.
* no answer / timeout - the host is off, unreachable, or Docker is down.

All three of the last two cases mean "do not trust the silence", so this
script alerts on any non-200 and on any connection failure.

Stdlib only. No pip install. Python 3.9+.

Config via environment variables:

  NURBY_BEACON_URL      required, e.g. https://nurby.example.com/api/beacon
  NURBY_TIMEOUT         seconds to wait for the beacon (default 10)
  NURBY_FAIL_THRESHOLD  consecutive bad polls before alerting (default 2)
  NURBY_STATE_FILE      path to persist state between runs
                        (default: ./nurby_watchdog_state.json)

  # Choose at least one alert channel (off-box!):
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID   alert via Telegram
  SMTP_HOST + SMTP_PORT + ALERT_EMAIL_TO  alert via email
      optional: SMTP_USER, SMTP_PASS, ALERT_EMAIL_FROM, SMTP_STARTTLS=1

Exit code is 0 on a healthy poll, 1 when the beacon is bad. That lets you
also wire it into an uptime service that only understands exit codes.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if (v is not None and v != "") else default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def poll(url: str, timeout: float) -> tuple[bool, str]:
    """Return (healthy, detail). healthy is True only on HTTP 200."""
    req = urllib.request.Request(url, headers={"User-Agent": "nurby-watchdog/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", "replace")
            return resp.status == 200, f"HTTP {resp.status}: {body[:300]}"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(4096).decode("utf-8", "replace")
        except Exception:
            pass
        # A 503 from the beacon is a real, parseable "degraded" answer.
        return False, f"HTTP {e.code}: {body[:300]}"
    except Exception as e:  # timeout, DNS, connection refused, TLS, ...
        return False, f"unreachable: {type(e).__name__}: {e}"


def _load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"consecutive_failures": 0, "alerted": False}


def _save_state(path: str, state: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[watchdog] warning: could not write state file {path}: {e}", file=sys.stderr)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as resp:
        resp.read()


def send_email(subject: str, body: str) -> None:
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "587"))
    to_addr = _env("ALERT_EMAIL_TO")
    from_addr = _env("ALERT_EMAIL_FROM", to_addr)
    if not (host and to_addr):
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=20) as s:
        if _env("SMTP_STARTTLS", "1") == "1":
            s.starttls(context=ssl.create_default_context())
        user, pw = _env("SMTP_USER"), _env("SMTP_PASS")
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)


def dispatch_alert(subject: str, body: str) -> bool:
    """Send through every configured off-box channel. Returns True if at
    least one channel accepted the message."""
    sent = False
    tg_token, tg_chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        try:
            send_telegram(tg_token, tg_chat, f"{subject}\n\n{body}")
            sent = True
        except Exception as e:
            print(f"[watchdog] telegram send failed: {e}", file=sys.stderr)
    if _env("SMTP_HOST") and _env("ALERT_EMAIL_TO"):
        try:
            send_email(subject, body)
            sent = True
        except Exception as e:
            print(f"[watchdog] email send failed: {e}", file=sys.stderr)
    if not sent:
        print(f"[watchdog] NO CHANNEL CONFIGURED. would have sent: {subject}", file=sys.stderr)
    return sent


def main() -> int:
    url = _env("NURBY_BEACON_URL")
    if not url:
        print("[watchdog] NURBY_BEACON_URL is required", file=sys.stderr)
        return 2
    timeout = float(_env("NURBY_TIMEOUT", "10"))
    threshold = int(_env("NURBY_FAIL_THRESHOLD", "2"))
    state_file = _env("NURBY_STATE_FILE", "./nurby_watchdog_state.json")

    healthy, detail = poll(url, timeout)
    state = _load_state(state_file)

    if healthy:
        # Recovery: if we had alerted, send an all-clear once.
        if state.get("alerted"):
            dispatch_alert(
                "✅ Nurby is reporting again",
                f"The beacon at {url} returned healthy at {_now()}.\n{detail}",
            )
        state = {"consecutive_failures": 0, "alerted": False, "last_ok": _now()}
        _save_state(state_file, state)
        print(f"[watchdog] ok: {detail}")
        return 0

    # Unhealthy poll.
    state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
    print(
        f"[watchdog] bad poll {state['consecutive_failures']}/{threshold}: {detail}",
        file=sys.stderr,
    )
    if state["consecutive_failures"] >= threshold and not state.get("alerted"):
        dispatch_alert(
            "🚨 Nurby stopped reporting",
            (
                f"Nurby's monitoring beacon has been unreachable or degraded for "
                f"{state['consecutive_failures']} consecutive checks as of {_now()}.\n\n"
                f"Last detail: {detail}\n"
                f"Beacon: {url}\n\n"
                "Your cameras may be effectively unmonitored. Check the Nurby host "
                "(power, network, Docker) as soon as you can."
            ),
        )
        state["alerted"] = True
    _save_state(state_file, state)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
