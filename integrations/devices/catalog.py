"""Device preset catalog.

Each preset is presentational data the frontend renders in the rule
builder, plus a ``webhook_action`` template the user drops into a rule.
The ``{ip}``, ``{port}``, and ``{secret}`` placeholders are filled in by
the UI from the device fields the user enters. Receiver scripts live
under ``integrations/devices/receivers/`` and are referenced by path so
the docs and a future "copy script" button can serve them.

Keep this pure data. no imports, no side effects, so it is safe to load
from the API process and from docs tooling alike.
"""
from __future__ import annotations

# The standard payload every receiver script expects. Documented once
# here and reused as the default payload_template for each preset.
STANDARD_PAYLOAD = {
    "event": "{rule_name}",
    "camera": "{camera_name}",
    "time": "{timestamp_local}",
    "description": "{detections_summary}",
    "recording_url": "{recording_url}",
    "thumbnail_url": "{thumbnail_url}",
}


DEVICE_PRESETS: list[dict] = [
    {
        "id": "esp32-buzzer-alarm",
        "name": "ESP32 Buzzer Alarm",
        "category": "alarm",
        "platform": "ESP32",
        "summary": "A pocket-size Wi-Fi alarm. Sounds a piezo buzzer pattern when an alert fires.",
        "hardware": [
            "ESP32 dev board (any variant)",
            "Active piezo buzzer (or a passive buzzer on a PWM pin)",
            "Two jumper wires",
        ],
        "wiring": "Buzzer + to GPIO 23. Buzzer - to GND. Power the ESP32 over USB.",
        "receiver": "integrations/devices/receivers/esp32_buzzer_alarm.ino",
        "receiver_language": "arduino",
        "default_port": 80,
        "supports_hmac": True,
        "webhook_action": {
            "type": "webhook",
            "url": "http://{ip}:{port}/alert",
            "secret": "{secret}",
            "payload_template": STANDARD_PAYLOAD,
            "timeout": 5,
        },
        "steps": [
            "Flash esp32_buzzer_alarm.ino with the Arduino IDE. Set WIFI_SSID, WIFI_PASS, and SHARED_SECRET at the top.",
            "Open the Serial Monitor at 115200 baud and note the IP address the board prints on boot.",
            "In Nurby, add a webhook action to your rule and pick this device. Enter that IP.",
            "Fire a test event. The buzzer should chirp three times.",
        ],
    },
    {
        "id": "esp8266-relay-lights",
        "name": "ESP8266 Relay Lights",
        "category": "lights",
        "platform": "ESP8266",
        "summary": "Switches a mains lamp, strobe, or siren through a relay for a few seconds on alert.",
        "hardware": [
            "ESP8266 board (Wemos D1 mini or NodeMCU)",
            "5V relay module (opto-isolated)",
            "A lamp, strobe, or 12V siren wired through the relay",
        ],
        "wiring": "Relay IN to GPIO 5 (D1). Relay VCC to 5V, GND to GND. Switch your load through the relay's COM/NO terminals. Mains wiring is mandatory to do safely. use a pre-built relay enclosure if unsure.",
        "receiver": "integrations/devices/receivers/esp8266_relay_lights.ino",
        "receiver_language": "arduino",
        "default_port": 80,
        "supports_hmac": True,
        "webhook_action": {
            "type": "webhook",
            "url": "http://{ip}:{port}/alert",
            "secret": "{secret}",
            "payload_template": STANDARD_PAYLOAD,
            "timeout": 5,
        },
        "steps": [
            "Flash esp8266_relay_lights.ino. Set Wi-Fi creds, SHARED_SECRET, and HOLD_MS (how long the light stays on).",
            "Read the board's IP from the Serial Monitor.",
            "Add a webhook action in Nurby pointed at that IP and pick this device.",
            "Test the rule. The relay should click and the load switch on for HOLD_MS.",
        ],
    },
    {
        "id": "raspberry-pi-speaker",
        "name": "Raspberry Pi Speaker",
        "category": "speaker",
        "platform": "Raspberry Pi",
        "summary": "Speaks the alert out loud (text to speech) or plays a sound file through the Pi's audio out.",
        "hardware": [
            "Raspberry Pi (any model with networking)",
            "A speaker on the 3.5mm jack, USB, or HDMI audio",
        ],
        "wiring": "Plug a speaker into the Pi. No GPIO wiring needed.",
        "receiver": "integrations/devices/receivers/raspberry_pi_speaker.py",
        "receiver_language": "python",
        "default_port": 8088,
        "supports_hmac": True,
        "webhook_action": {
            "type": "webhook",
            "url": "http://{ip}:{port}/alert",
            "secret": "{secret}",
            "payload_template": STANDARD_PAYLOAD,
            "timeout": 5,
        },
        "steps": [
            "Copy raspberry_pi_speaker.py to the Pi. Install deps. pip install flask, and apt install espeak-ng for speech.",
            "Run NURBY_DEVICE_SECRET=yoursecret python3 raspberry_pi_speaker.py. It listens on port 8088.",
            "Find the Pi's IP with hostname -I.",
            "Add a webhook action in Nurby pointed at that IP and pick this device. The Pi announces each alert.",
        ],
    },
    {
        "id": "raspberry-pi-relay-alarm",
        "name": "Raspberry Pi Relay Alarm",
        "category": "alarm",
        "platform": "Raspberry Pi",
        "summary": "Drives a GPIO relay to trigger a 12V siren or strobe for a set duration on alert.",
        "hardware": [
            "Raspberry Pi (any model with GPIO)",
            "5V relay module",
            "12V siren or strobe with its own power supply",
        ],
        "wiring": "Relay IN to GPIO 17 (pin 11). Relay VCC to 5V (pin 2), GND to GND (pin 6). Switch the siren's 12V supply through the relay COM/NO.",
        "receiver": "integrations/devices/receivers/raspberry_pi_relay_alarm.py",
        "receiver_language": "python",
        "default_port": 8089,
        "supports_hmac": True,
        "webhook_action": {
            "type": "webhook",
            "url": "http://{ip}:{port}/alert",
            "secret": "{secret}",
            "payload_template": STANDARD_PAYLOAD,
            "timeout": 5,
        },
        "steps": [
            "Copy raspberry_pi_relay_alarm.py to the Pi. Install deps. pip install flask gpiozero.",
            "Run NURBY_DEVICE_SECRET=yoursecret python3 raspberry_pi_relay_alarm.py. It listens on port 8089.",
            "Wire the relay per the diagram and find the Pi's IP with hostname -I.",
            "Add a webhook action in Nurby pointed at that IP and pick this device. The siren fires for SIREN_SECONDS.",
        ],
    },
]


def get_preset(preset_id: str) -> dict | None:
    """Return a preset by id, or None."""
    for p in DEVICE_PRESETS:
        if p["id"] == preset_id:
            return p
    return None
