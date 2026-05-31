#!/usr/bin/env python3
"""Nurby Raspberry Pi Relay Alarm receiver.

Fires a GPIO-driven relay (siren or strobe) for SIREN_SECONDS when a
Nurby alert arrives. Optional HMAC verification.

Wiring:
    Relay IN  -> GPIO 17 (physical pin 11)
    Relay VCC -> 5V      (pin 2)
    Relay GND -> GND     (pin 6)
    Switch a 12V siren/strobe (own power supply) through relay COM/NO.

Setup on the Pi:
    pip install flask gpiozero
    NURBY_DEVICE_SECRET=yoursecret python3 raspberry_pi_relay_alarm.py

Point a Nurby webhook action at http://<pi-ip>:8089/alert and set the
same secret on the action.
"""
import hashlib
import hmac
import os
import threading
import time

from flask import Flask, request

try:
    from gpiozero import OutputDevice
except Exception:  # pragma: no cover - only present on a Pi
    OutputDevice = None

app = Flask(__name__)

SECRET = os.environ.get("NURBY_DEVICE_SECRET", "")
PORT = int(os.environ.get("NURBY_DEVICE_PORT", "8089"))
RELAY_GPIO = int(os.environ.get("NURBY_RELAY_GPIO", "17"))
SIREN_SECONDS = float(os.environ.get("NURBY_SIREN_SECONDS", "8"))

_relay = OutputDevice(RELAY_GPIO, active_high=True, initial_value=False) if OutputDevice else None
_lock = threading.Lock()


def signature_ok(body: bytes) -> bool:
    if not SECRET:
        return True
    sent = request.headers.get("X-Nurby-Signature", "")
    want = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, want)


def fire_siren() -> None:
    # Non-blocking. one burst at a time. re-triggers are ignored while
    # the siren is already sounding.
    if not _lock.acquire(blocking=False):
        return
    try:
        if _relay:
            _relay.on()
        time.sleep(SIREN_SECONDS)
    finally:
        if _relay:
            _relay.off()
        _lock.release()


@app.post("/alert")
def alert():
    raw = request.get_data()
    if not signature_ok(raw):
        return {"ok": False, "error": "bad signature"}, 401
    print("ALERT:", request.get_json(silent=True) or {})
    threading.Thread(target=fire_siren, daemon=True).start()
    return {"ok": True}


@app.get("/")
def health():
    return {"ok": True, "device": "nurby-raspberry-pi-relay-alarm",
            "gpio_available": _relay is not None}


if __name__ == "__main__":
    print(f"Nurby relay alarm listening on :{PORT} "
          f"(GPIO {RELAY_GPIO}, {SIREN_SECONDS}s burst, "
          f"signature check {'on' if SECRET else 'off'})")
    app.run(host="0.0.0.0", port=PORT)
