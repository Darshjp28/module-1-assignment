"""
Task 1.1 — MQTT Sensor Publisher
SmartFactory IoT Protocol Integration
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PUBLISHER] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
BROKER_HOST: str = "localhost"
BROKER_PORT: int = 1883
KEEPALIVE: int = 60
PUBLISH_INTERVAL: float = 1.0  # seconds

LINES: list[str] = ["line1", "line2"]
SENSOR_TYPES: list[str] = ["temperature", "vibration", "power"]

# QoS per sensor type (spec: temp=1, vibration=0, power=2)
QOS_MAP: dict[str, int] = {
    "temperature": 1,
    "vibration": 0,
    "power": 2,
}

UNITS: dict[str, str] = {
    "temperature": "°C",
    "vibration": "mm/s",
    "power": "kW",
}

CRITICAL_TEMP: float = 85.0


# ── Value generators ───────────────────────────────────────────────────────────

def _generate_value(sensor_type: str) -> float:
    """Return a realistic simulated sensor reading."""
    if sensor_type == "temperature":
        # Occasionally spike above critical threshold so alerts fire in tests
        if random.random() < 0.10:
            return round(random.uniform(85.5, 98.0), 2)
        return round(random.uniform(60.0, 84.9), 2)
    elif sensor_type == "vibration":
        return round(random.uniform(0.1, 5.0), 2)
    elif sensor_type == "power":
        return round(random.uniform(10.0, 100.0), 2)
    return 0.0


def _build_payload(line: str, sensor_type: str, value: float) -> str:
    return json.dumps(
        {
            "line": line,
            "sensor": sensor_type,
            "value": value,
            "unit": UNITS[sensor_type],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


# ── MQTT callbacks ─────────────────────────────────────────────────────────────

def _on_connect(client: mqtt.Client, userdata: dict, flags: dict, rc: int) -> None:
    line: str = userdata["line"]
    if rc == 0:
        session_present = flags.get("session present", 0)
        logger.info(
            "Connected  line=%-5s  session_present=%s  broker=%s:%s",
            line, bool(session_present), BROKER_HOST, BROKER_PORT,
        )
        # Publish retained 'online' status on every (re)connect
        status_topic = f"factory/{line}/status"
        client.publish(status_topic, payload="online", qos=1, retain=True)
        logger.info("PUBLISH  topic=%-35s  payload=online  qos=1  retain=True", status_topic)
    else:
        logger.error("Connection refused  line=%s  rc=%d", line, rc)


def _on_publish(client: mqtt.Client, userdata: dict, mid: int) -> None:
    logger.debug("PUBACK received  mid=%d", mid)


def _on_disconnect(client: mqtt.Client, userdata: dict, rc: int) -> None:
    logger.warning("Disconnected  line=%s  rc=%d", userdata["line"], rc)


# ── Client factory ─────────────────────────────────────────────────────────────

def create_client(line: str) -> mqtt.Client:
    """
    Create and configure an MQTT client for *line* with:
    - Persistent session (clean_session=False)
    - Last Will and Testament on factory/{line}/status
    """
    client_id = f"smartfactory-publisher-{line}"

    # clean_session=False → persistent session
    client = mqtt.Client(client_id=client_id, clean_session=False)
    client.user_data_set({"line": line})

    # Last Will and Testament
    lwt_topic = f"factory/{line}/status"
    client.will_set(lwt_topic, payload="offline", qos=1, retain=True)

    client.on_connect = _on_connect
    client.on_publish = _on_publish
    client.on_disconnect = _on_disconnect

    return client


# ── Publisher loop ─────────────────────────────────────────────────────────────

def run_publisher() -> None:
    """Connect one client per production line and publish readings every second."""
    clients: dict[str, mqtt.Client] = {}

    for line in LINES:
        client = create_client(line)
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=KEEPALIVE)
        client.loop_start()
        clients[line] = client

    logger.info("Publishing sensor data for lines: %s", LINES)

    try:
        while True:
            for line in LINES:
                client = clients[line]
                for sensor_type in SENSOR_TYPES:
                    value = _generate_value(sensor_type)
                    qos = QOS_MAP[sensor_type]
                    topic = f"factory/{line}/{sensor_type}"
                    payload = _build_payload(line, sensor_type, value)

                    result = client.publish(topic, payload=payload, qos=qos)

                    logger.info(
                        "PUBLISH  topic=%-35s  value=%7.2f %-5s  qos=%d  mid=%d",
                        topic, value, UNITS[sensor_type], qos, result.mid,
                    )

                    if sensor_type == "temperature" and value > CRITICAL_TEMP:
                        logger.warning(
                            "⚠  CRITICAL TEMP  line=%-5s  value=%.2f°C",
                            line, value,
                        )

            time.sleep(PUBLISH_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Shutdown requested — disconnecting clients…")
    finally:
        for line, client in clients.items():
            # LWT fires automatically on ungraceful disconnect;
            # here we publish explicit 'offline' before clean disconnect.
            client.publish(f"factory/{line}/status", payload="offline", qos=1, retain=True)
            client.loop_stop()
            client.disconnect()
        logger.info("All clients disconnected.")


if __name__ == "__main__":
    run_publisher()
