"""
tests/mqtt/test_publisher.py
Unit tests for src/mqtt/publisher.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _import_publisher():
    from src.mqtt import publisher
    return publisher


# ── test_connect_persistent ────────────────────────────────────────────────────

def test_connect_persistent():
    """create_client() must use clean_session=False for a persistent session."""
    pub = _import_publisher()

    with patch("paho.mqtt.client.Client") as MockClient:
        instance = MockClient.return_value
        pub.create_client("line1")
        # The Client constructor must be called with clean_session=False
        args, kwargs = MockClient.call_args
        assert kwargs.get("clean_session") is False or (
            len(args) > 1 and args[1] is False
        ), "Client must be created with clean_session=False"


# ── test_publishes_correct_topics ──────────────────────────────────────────────

def test_publishes_correct_topics():
    """All 6 sensor topics must follow factory/{line}/{sensor_type} hierarchy."""
    pub = _import_publisher()

    expected = {
        "factory/line1/temperature",
        "factory/line1/vibration",
        "factory/line1/power",
        "factory/line2/temperature",
        "factory/line2/vibration",
        "factory/line2/power",
    }
    actual = {
        f"factory/{line}/{sensor}"
        for line in pub.LINES
        for sensor in pub.SENSOR_TYPES
    }
    assert actual == expected


# ── test_lwt_configured ───────────────────────────────────────────────────────

def test_lwt_configured():
    """LWT must target factory/{line}/status with payload='offline', qos=1, retain=True."""
    pub = _import_publisher()

    with patch("paho.mqtt.client.Client") as MockClient:
        instance = MockClient.return_value
        pub.create_client("line1")
        instance.will_set.assert_called_once_with(
            "factory/line1/status",
            payload="offline",
            qos=1,
            retain=True,
        )


# ── test_qos_map ──────────────────────────────────────────────────────────────

def test_qos_map():
    """temperature=QoS 1, vibration=QoS 0, power=QoS 2."""
    pub = _import_publisher()
    assert pub.QOS_MAP["temperature"] == 1
    assert pub.QOS_MAP["vibration"] == 0
    assert pub.QOS_MAP["power"] == 2


# ── test_generate_value_ranges ────────────────────────────────────────────────

def test_generate_value_ranges():
    """Generated sensor values must fall within expected physical ranges."""
    pub = _import_publisher()

    for _ in range(200):
        t = pub._generate_value("temperature")
        assert 60.0 <= t <= 98.0, f"Temperature {t} out of range"

        v = pub._generate_value("vibration")
        assert 0.1 <= v <= 5.0, f"Vibration {v} out of range"

        p = pub._generate_value("power")
        assert 10.0 <= p <= 100.0, f"Power {p} out of range"


# ── test_client_id_per_line ───────────────────────────────────────────────────

def test_client_id_per_line():
    """Each line must get a unique, deterministic client ID."""
    pub = _import_publisher()

    with patch("paho.mqtt.client.Client") as MockClient:
        MockClient.return_value = MagicMock()
        pub.create_client("line1")
        _, kwargs1 = MockClient.call_args
        client_id_1 = kwargs1.get("client_id", MockClient.call_args[0][0] if MockClient.call_args[0] else "")

    with patch("paho.mqtt.client.Client") as MockClient:
        MockClient.return_value = MagicMock()
        pub.create_client("line2")
        _, kwargs2 = MockClient.call_args
        client_id_2 = kwargs2.get("client_id", MockClient.call_args[0][0] if MockClient.call_args[0] else "")

    assert client_id_1 != client_id_2, "Each line must have a unique client ID"
    assert "line1" in client_id_1
    assert "line2" in client_id_2
