"""
Task 1.2 — MQTT Wildcard Subscriber
SmartFactory IoT Protocol Integration
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SUBSCRIBER] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
BROKER_HOST: str = "localhost"
BROKER_PORT: int = 1883
KEEPALIVE: int = 60
SUMMARY_INTERVAL: float = 30.0   # seconds
CRITICAL_TEMP: float = 85.0

CLIENT_ID: str = "smartfactory-subscriber"


# ── Shared state ───────────────────────────────────────────────────────────────
_message_counts: dict[str, int] = defaultdict(int)
_lock = threading.Lock()


# ── MQTT callbacks ─────────────────────────────────────────────────────────────

def _on_connect(client: mqtt.Client, userdata, flags: dict, rc: int) -> None:
    if rc == 0:
        logger.info(
            "Connected  broker=%s:%s  session_present=%s",
            BROKER_HOST, BROKER_PORT, bool(flags.get("session present", 0)),
        )
        # Wildcard — all sensor readings + status messages
        client.subscribe("factory/#", qos=1)
        logger.info("Subscribed  filter=factory/#  qos=1")

        # Separate high-reliability subscription for temperature topics
        client.subscribe("factory/+/temperature", qos=2)
        logger.info("Subscribed  filter=factory/+/temperature  qos=2")
    else:
        logger.error("Connection refused  rc=%d", rc)


def _parse_payload(raw: bytes) -> tuple[dict | str, bool]:
    """Return (parsed_value, is_json)."""
    try:
        return json.loads(raw.decode("utf-8")), True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace"), False


def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    topic: str = msg.topic
    qos: int = msg.qos
    retain: bool = bool(msg.retain)
    payload, is_json = _parse_payload(msg.payload)

    logger.info(
        "RECV  topic=%-40s  qos=%d  retain=%-5s  payload=%s",
        topic, qos, retain, payload,
    )

    with _lock:
        _message_counts[topic] += 1

    # ── Critical temperature alert ─────────────────────────────────────────────
    if is_json and "temperature" in topic:
        value: float = payload.get("value", 0.0)
        line: str = payload.get("line", "unknown")
        ts: str = payload.get("timestamp", datetime.now(timezone.utc).isoformat())

        if value > CRITICAL_TEMP:
            logger.warning(
                "🚨 CRITICAL ALERT | line=%-5s | sensor=temperature | "
                "value=%.2f°C | threshold=%.1f°C | timestamp=%s",
                line, value, CRITICAL_TEMP, ts,
            )


def _on_disconnect(client: mqtt.Client, userdata, rc: int) -> None:
    logger.warning("Disconnected  rc=%d", rc)


# ── Periodic summary ───────────────────────────────────────────────────────────

def _summary_loop() -> None:
    """Print a message-count summary every SUMMARY_INTERVAL seconds."""
    while True:
        time.sleep(SUMMARY_INTERVAL)
        with _lock:
            snapshot = dict(_message_counts)

        total = sum(snapshot.values())
        logger.info("━" * 60)
        logger.info("30-SECOND MESSAGE SUMMARY  (total=%d)", total)
        for topic in sorted(snapshot):
            logger.info("  %-45s  %4d msgs", topic, snapshot[topic])
        logger.info("━" * 60)


# ── Entry point ────────────────────────────────────────────────────────────────

def run_subscriber() -> None:
    client = mqtt.Client(client_id=CLIENT_ID, clean_session=False)
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.on_disconnect = _on_disconnect

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=KEEPALIVE)

    # Background summary thread
    summary_thread = threading.Thread(target=_summary_loop, daemon=True)
    summary_thread.start()

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    finally:
        client.disconnect()
        logger.info("Subscriber disconnected.")


if __name__ == "__main__":
    run_subscriber()
