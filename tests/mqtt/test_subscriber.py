"""
tests/mqtt/test_subscriber.py
Unit tests for src/mqtt/subscriber.py
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest


def _make_mqtt_message(topic: str, payload: dict | str, qos: int = 1, retain: bool = False):
    """Build a minimal mock MQTTMessage."""
    msg = MagicMock()
    msg.topic = topic
    msg.qos = qos
    msg.retain = int(retain)
    if isinstance(payload, dict):
        msg.payload = json.dumps(payload).encode()
    else:
        msg.payload = str(payload).encode()
    return msg


# ── test_wildcard_subscription ────────────────────────────────────────────────

def test_wildcard_subscription():
    """Subscriber must subscribe to 'factory/#'."""
    from src.mqtt import subscriber

    mock_client = MagicMock()
    subscriber._on_connect(mock_client, {}, {"session present": 0}, rc=0)

    subscribed_topics = [args[0] for args, _ in mock_client.subscribe.call_args_list]
    assert "factory/#" in subscribed_topics, "Missing wildcard subscription to factory/#"


# ── test_temperature_subscription_qos2 ───────────────────────────────────────

def test_temperature_subscription_qos2():
    """Subscriber must subscribe to 'factory/+/temperature' at QoS 2."""
    from src.mqtt import subscriber

    mock_client = MagicMock()
    subscriber._on_connect(mock_client, {}, {"session present": 0}, rc=0)

    temp_calls = [
        (args, kwargs)
        for args, kwargs in mock_client.subscribe.call_args_list
        if args[0] == "factory/+/temperature"
    ]
    assert temp_calls, "Missing subscription to factory/+/temperature"
    # QoS must be 2
    args, kwargs = temp_calls[0]
    qos = args[1] if len(args) > 1 else kwargs.get("qos")
    assert qos == 2, f"Expected QoS 2 for temperature subscription, got {qos}"


# ── test_critical_alert_fires ─────────────────────────────────────────────────

def test_critical_alert_fires(caplog):
    """A temperature reading > 85°C must emit a CRITICAL ALERT log entry."""
    import logging
    from src.mqtt import subscriber

    mock_client = MagicMock()
    msg = _make_mqtt_message(
        topic="factory/line1/temperature",
        payload={"line": "line1", "sensor": "temperature", "value": 91.5, "timestamp": "2026-05-22T10:00:00Z"},
        qos=1,
    )

    with caplog.at_level(logging.WARNING):
        subscriber._on_message(mock_client, {}, msg)

    alert_logs = [r for r in caplog.records if "CRITICAL" in r.message.upper()]
    assert alert_logs, "No CRITICAL ALERT emitted for temperature 91.5°C"


# ── test_no_alert_below_threshold ─────────────────────────────────────────────

def test_no_alert_below_threshold(caplog):
    """A temperature reading <= 85°C must NOT emit a critical alert."""
    import logging
    from src.mqtt import subscriber

    mock_client = MagicMock()
    msg = _make_mqtt_message(
        topic="factory/line1/temperature",
        payload={"line": "line1", "sensor": "temperature", "value": 75.0, "timestamp": "2026-05-22T10:00:00Z"},
        qos=1,
    )

    with caplog.at_level(logging.WARNING):
        subscriber._on_message(mock_client, {}, msg)

    alert_logs = [r for r in caplog.records if "CRITICAL" in r.message.upper()]
    assert not alert_logs, "Unexpected CRITICAL ALERT for temperature 75.0°C"


# ── test_message_counter_increments ──────────────────────────────────────────

def test_message_counter_increments():
    """Message counter for each topic must increment on every received message."""
    from src.mqtt import subscriber

    subscriber._message_counts.clear()

    mock_client = MagicMock()
    topic = "factory/line1/vibration"
    msg = _make_mqtt_message(
        topic=topic,
        payload={"line": "line1", "sensor": "vibration", "value": 1.2},
    )

    subscriber._on_message(mock_client, {}, msg)
    subscriber._on_message(mock_client, {}, msg)
    subscriber._on_message(mock_client, {}, msg)

    assert subscriber._message_counts[topic] == 3
