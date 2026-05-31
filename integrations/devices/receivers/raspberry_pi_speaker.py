#!/usr/bin/env python3
"""Nurby Raspberry Pi Speaker receiver.

Announces each Nurby alert out loud. Speaks the event text with
espeak-ng, or plays a sound file if you set NURBY_SOUND_FILE.

Setup on the Pi:
    pip install flask
    sudo apt install espeak-ng        # for text to speech
    NURBY_DEVICE_SECRET=yoursecret python3 raspberry_pi_speaker.py

Then point a Nurby webhook action at http://<pi-ip>:8088/alert and set
the same secret on the action so signatures verify. Leave the secret
unset on a trusted home LAN to skip verification.

Payload Nurby sends (the device preset's default template):
    { "event", "camera", "time", "description", "recording_url", ... }
"""
import hashlib
import hmac
import os
import subprocess

from flask import Flask, request

app = Flask(__name__)

SECRET = os.environ.get("NURBY_DEVICE_SECRET", "")
PORT = int(os.environ.get("NURBY_DEVICE_PORT", "8088"))
SOUND_FILE = os.environ.get("NURBY_SOUND_FILE", "")  # optional .wav/.mp3


def signature_ok(body: bytes) -> bool:
    if not SECRET:
        return True  # verification disabled
    sent = request.headers.get("X-Nurby-Signature", "")
    want = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, want)


def announce(text: str) -> None:
    if SOUND_FILE:
        # Play a fixed chime/sound instead of speaking.
        player = "mpg123" if SOUND_FILE.endswith(".mp3") else "aplay"
        subprocess.Popen([player, SOUND_FILE])
        return
    subprocess.Popen(["espeak-ng", text])


@app.post("/alert")
def alert():
    raw = request.get_data()
    if not signature_ok(raw):
        return {"ok": False, "error": "bad signature"}, 401
    data = request.get_json(silent=True) or {}
    event = data.get("event", "an event")
    camera = data.get("camera", "a camera")
    spoken = f"Nurby alert. {event} on {camera}."
    print("ALERT:", data)
    announce(spoken)
    return {"ok": True}


@app.get("/")
def health():
    return {"ok": True, "device": "nurby-raspberry-pi-speaker"}


if __name__ == "__main__":
    print(f"Nurby speaker listening on :{PORT} "
          f"(signature check {'on' if SECRET else 'off'})")
    app.run(host="0.0.0.0", port=PORT)
