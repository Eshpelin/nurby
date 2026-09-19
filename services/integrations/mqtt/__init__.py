"""MQTT / Home Assistant integration (docs/integrations/mqtt.md).

One broker connection (the bridge supervisor in the API process)
publishes Nurby's topic tree plus Home Assistant discovery configs;
producers in every process fan in through the Redis bus
(``shared/mqtt_bus``).
"""

from services.integrations.mqtt.bridge import MqttBridge, get_bridge, bridge_status
from services.integrations.mqtt.config import MqttConfig, load_config

__all__ = [
    "MqttBridge",
    "MqttConfig",
    "bridge_status",
    "get_bridge",
    "load_config",
]
