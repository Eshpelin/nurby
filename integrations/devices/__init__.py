"""Out-of-box physical alert device presets and receiver scripts.

A device preset maps a real piece of hardware (an ESP32 buzzer, a
Raspberry Pi speaker, a relay-driven siren or lights) to a ready-to-use
Nurby webhook action plus a receiver script that runs on the device.
The rule builder surfaces these so a user can pick "ESP32 Buzzer Alarm"
and get a pre-filled webhook action pointed at their device.
"""
from integrations.devices.catalog import DEVICE_PRESETS, get_preset

__all__ = ["DEVICE_PRESETS", "get_preset"]
