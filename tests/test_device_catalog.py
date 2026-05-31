import os

from integrations.devices import DEVICE_PRESETS, get_preset

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)


def test_presets_have_required_fields():
    assert DEVICE_PRESETS
    for p in DEVICE_PRESETS:
        for key in ("id", "name", "category", "platform", "webhook_action", "receiver", "steps"):
            assert key in p, f"{p.get('id')} missing {key}"
        action = p["webhook_action"]
        assert action["type"] == "webhook"
        assert "{ip}" in action["url"]


def test_preset_ids_unique():
    ids = [p["id"] for p in DEVICE_PRESETS]
    assert len(ids) == len(set(ids))


def test_get_preset_roundtrip():
    assert get_preset("esp32-buzzer-alarm")["platform"] == "ESP32"
    assert get_preset("nope") is None


def test_every_receiver_script_exists():
    for p in DEVICE_PRESETS:
        path = os.path.join(_REPO_ROOT, p["receiver"])
        assert os.path.isfile(path), f"missing receiver for {p['id']}: {p['receiver']}"
        assert os.path.getsize(path) > 0
